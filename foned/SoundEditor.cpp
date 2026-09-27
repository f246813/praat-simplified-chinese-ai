/* SoundEditor.cpp
 *
 * Copyright (C) 1992-2022 Paul Boersma
 *
 * This code is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or (at
 * your option) any later version.
 *
 * This code is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 * See the GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this work. If not, see <http://www.gnu.org/licenses/>.
 */

#include "SoundEditor.h"
#include "EditorM.h"
#include "../fon/SegmentAcousticVOT.h"
#include "melder_progress.h"
#include "PraatAiControl.h"
#include "Gui.h"
#include "praat.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <exception>
#include <limits>
#include <string>
#include <thread>

Thing_implement (SoundEditor, FunctionEditor, 0);

static void menu_cb_SoundEditorHelp (SoundEditor, EDITOR_ARGS) { Melder_help (U"SoundEditor"); }
static void menu_cb_LongSoundEditorHelp (SoundEditor, EDITOR_ARGS) { Melder_help (U"LongSoundEditor"); }

static std::optional<double> editorOptionalVotBoundary (double value) {
	return isundef (value) ? std::optional<double> {} : std::optional<double> { value };
}

static constexpr integer VOT_FORM_BURST_FIELD_INDEX = 3;
static constexpr integer VOT_FORM_VOICING_FIELD_INDEX = 4;
static constexpr integer VOT_FORM_PROGRESS_FIELD_INDEX = 6;
static constexpr integer VOT_FORM_CONTEXT_START_FIELD_INDEX = 8;
static constexpr integer VOT_FORM_CONTEXT_END_FIELD_INDEX = 9;

static UiField votFormBoundaryField (UiForm form, integer fieldIndex) {
	if (! form || form -> numberOfFields < fieldIndex)
		return nullptr;
	return form -> field [fieldIndex].get();
}

static UiField votFormValueDisplayField (UiForm form) {
	if (! form)
		return nullptr;
	for (integer i = 1; i <= form -> numberOfFields; i ++) {
		UiField field = form -> field [i].get();
		if (field -> type == _kUiField_type::COMMENT_ && field -> stringVariable && field -> stringValue &&
			str32str (field -> stringValue.get(), U"VOT 值（ms）："))
			return field;
	}
	return nullptr;
}

static std::string votJsonStringField (const std::string &json, const std::string &name) {
	const std::string key = "\"" + name + "\"";
	const size_t keyPosition = json.find (key);
	if (keyPosition == std::string::npos)
		return {};
	const size_t colon = json.find (':', keyPosition + key.size());
	const size_t quote = colon == std::string::npos ? std::string::npos : json.find ('"', colon + 1);
	if (quote == std::string::npos)
		return {};
	std::string value;
	for (size_t position = quote + 1; position < json.size(); position ++) {
		const char character = json [position];
		if (character == '"')
			return value;
		if (character != '\\' || position + 1 >= json.size()) {
			value += character;
			continue;
		}
		const char escaped = json [++ position];
		if (escaped == 'n') value += '\n';
		else if (escaped == 'r') value += '\r';
		else if (escaped == 't') value += '\t';
		else value += escaped;
	}
	return {};
}

static double votJsonNumberField (const std::string &json, const std::string &name, double fallback) {
	const std::string key = "\"" + name + "\"";
	const size_t keyPosition = json.find (key);
	if (keyPosition == std::string::npos)
		return fallback;
	const size_t colon = json.find (':', keyPosition + key.size());
	if (colon == std::string::npos)
		return fallback;
	const size_t valueStart = json.find_first_not_of (" \t\r\n", colon + 1);
	if (valueStart == std::string::npos)
		return fallback;
	char *end = nullptr;
	const double value = std::strtod (json.c_str() + valueStart, & end);
	return end != json.c_str() + valueStart && std::isfinite (value) ? value : fallback;
}

static integer editorSampleIndexAtTime (SampledXY audio, double time) {
	if (! audio || ! std::isfinite (time) || audio -> dx <= 0.0)
		return -1;
	const double domainStart = audio -> x1 - 0.5 * audio -> dx;
	const double domainEnd = audio -> x1 + (audio -> nx - 0.5) * audio -> dx;
	const double timeScale = std::max ({ 1.0, std::abs (time), std::abs (domainStart),
		std::abs (domainEnd), std::abs (audio -> x1) });
	const double domainTolerance = 8.0 * std::numeric_limits <double> :: epsilon() * timeScale;
	if (time < domainStart - domainTolerance || time > domainEnd + domainTolerance)
		return -1;
	return std::clamp (Melder_iround ((time - audio -> x1) / audio -> dx), (integer) 0, audio -> nx);
}

static double editorTimeAtSample (SampledXY audio, integer sample) {
	return audio -> x1 + sample * audio -> dx;
}

static void setVotResultFailure (SoundEditor me, conststring32 reason) {
	my votValueMs.reset();
	my votResultStatus = U"failed";
	my votFailureReason = reason ? reason : U"分析没有返回有效结果。";
	my votCalculationAttempted = true;
	my votNeedsRecalculation = false;
}

static UiField votFormProgressField (UiForm form) {
	return form && form -> numberOfFields >= VOT_FORM_PROGRESS_FIELD_INDEX ?
		form -> field [VOT_FORM_PROGRESS_FIELD_INDEX].get() : nullptr;
}

static void appendVotDisplayText (SoundEditor me, MelderString *text) {
	MelderString_empty (text);
	MelderString_append (text, U"VOT 值（ms）：");
	if (my votNeedsRecalculation) {
		MelderString_append (text, my votResultStatus == U"stale" ? U"结果已过期" : U"待计算");
		if (! my votFailureReason.empty())
			MelderString_append (text, U"：", my votFailureReason.c_str());
	} else if (! my votCalculationAttempted) {
		MelderString_append (text, U"尚未计算");
	} else if (! my votValueMs) {
		MelderString_append (text, U"无法计算");
		if (! my votFailureReason.empty())
			MelderString_append (text, U"：", my votFailureReason.c_str());
	} else {
		MelderString_append (text, Melder_fixed (my votValueMs.value(), 3), U" ms");
		if (my votValueIsCandidate)
			MelderString_append (text, U"（自动计算的候选值，待人工确认）");
		else if (my votResultStatus == U"manual_preview")
			MelderString_append (text, U"（手动预览，点击应用后确认）");
		else
			MelderString_append (text, U"（手动计算）");
	}
}

static void updateVotFormDisplay (UiForm form, SoundEditor me) {
	if (! form)
		return;
	UiField displayField = votFormValueDisplayField (form);
	if (! displayField)
		return;
	autoMelderString text;
	appendVotDisplayText (me, & text);
	UiForm_setString (form, displayField -> stringVariable, text.string);
	UiField progressField = votFormProgressField (form);
	if (progressField && progressField -> stringVariable)
		UiForm_setString (form, progressField -> stringVariable,
			my votProgressText.empty() ? U"分析进度：尚未开始" : my votProgressText.c_str());
}

static void setVotFormRealAtIndex (UiForm form, integer fieldIndex, double value) {
	UiField field = votFormBoundaryField (form, fieldIndex);
	if (field && field -> realVariable)
		UiForm_setReal (form, field -> realVariable, value);
}

static std::optional<double> readVotFormReal (UiField field) {
	if (! field || ! field -> text)
		return {};
	autostring32 text = GuiText_getString (field -> text);
	if (! text || ! Melder_isStringNumeric (text.get()))
		return {};
	const double value = Melder_atof (text.get());
	return std::isfinite (value) ? std::optional<double> { value } : std::optional<double> {};
}

static void setVotFormBoundaries (UiForm form, SoundEditor me) {
	if (! form)
		return;
	UiField burstField = votFormBoundaryField (form, VOT_FORM_BURST_FIELD_INDEX);
	UiField voicingField = votFormBoundaryField (form, VOT_FORM_VOICING_FIELD_INDEX);
	if (burstField && burstField -> realVariable)
		UiForm_setReal (form, burstField -> realVariable, my votBurstTime.value_or (undefined));
	if (voicingField && voicingField -> realVariable)
		UiForm_setReal (form, voicingField -> realVariable, my votVoicingTime.value_or (undefined));
}

static void updateManualVotFromForm (UiForm form, SoundEditor me) {
	const std::optional<double> burstTime = readVotFormReal (
		votFormBoundaryField (form, VOT_FORM_BURST_FIELD_INDEX));
	const std::optional<double> voicingTime = readVotFormReal (
		votFormBoundaryField (form, VOT_FORM_VOICING_FIELD_INDEX));
	my votManualConfirmed = false;
	my votValueIsCandidate = false;
	my votResultStatus = U"manual_preview";
	my votBurstTime = burstTime;
	my votVoicingTime = voicingTime;
	my votCalculationAttempted = true;
	my votNeedsRecalculation = false;
	my votFailureReason.clear();
	my votValueMs.reset();
	if (! burstTime || ! voicingTime) {
		my votFailureReason = U"手动计算需要同时填写爆破释放时刻和起声时刻。";
	} else {
		const SampledXY audio = static_cast <SampledXY> (my data());
		const integer burstSample = editorSampleIndexAtTime (audio, burstTime.value());
		const integer onsetSample = editorSampleIndexAtTime (audio, voicingTime.value());
		if (burstSample < 0 || onsetSample < 0 ||
			burstSample < editorSampleIndexAtTime (audio,
				my votFixedContextStartTime.value_or (audio -> x1 - 0.5 * audio -> dx)) ||
			onsetSample > editorSampleIndexAtTime (audio,
				my votFixedContextEndTime.value_or (audio -> x1 + (audio -> nx - 0.5) * audio -> dx)))
		{
			my votResultStatus = U"failed";
			my votFailureReason = U"手动边界必须落在当前固定分析上下文内。";
		} else {
			my votBurstTime = editorTimeAtSample (audio, burstSample);
			my votVoicingTime = editorTimeAtSample (audio, onsetSample);
			my votValueMs = (onsetSample - burstSample) * 1000.0 * audio -> dx;
			my votFailureReason.clear();
		}
	}
}

static double editorSelectionTimeAtSample (SampledXY audio, integer sample) {
	return audio -> x1 + (sample - 0.5) * audio -> dx;
}

static void cancelVotEditorJob (SoundEditor me) {
	if (my votCurrentJobId.empty())
		return;
	autostring32 jobId = Melder_8to32_e (my votCurrentJobId.c_str());
	PraatAiControl_cancelVOTJob (jobId.get());
	my votCurrentJobId.clear();
	my votRequestGeneration ++;
}

static void markVotResultStale (SoundEditor me, conststring32 reason) {
	cancelVotEditorJob (me);
	my votNeedsRecalculation = true;
	my votValueMs.reset();
	my votResultStatus = U"stale";
	my votFailureReason = reason ? reason : U"输入已改变；请重新提交分析。";
	my votProgressText = U"分析进度：结果已过期";
}

static void vot_gui_text_cb_changed (UiForm form, GuiTextEvent event) {
	SoundEditor me = static_cast <SoundEditor> (form -> optionalEditor);
	if (! me || my votUpdatingForm)
		return;
	UiField changedField = nullptr;
	for (integer i = 1; i <= form -> numberOfFields; i ++) {
		if (form -> field [i] -> text == event -> text) {
			changedField = form -> field [i].get();
			break;
		}
	}
	if (! changedField)
		return;
	const bool changedBoundary =
		changedField == votFormBoundaryField (form, VOT_FORM_BURST_FIELD_INDEX) ||
		changedField == votFormBoundaryField (form, VOT_FORM_VOICING_FIELD_INDEX);
	if (my votMode == 3 && changedBoundary) {
		updateManualVotFromForm (form, me);
	} else {
		if (! my votCurrentJobId.empty()) {
			autostring32 jobId = Melder_8to32_e (my votCurrentJobId.c_str());
			PraatAiControl_cancelVOTJob (jobId.get());
			my votCurrentJobId.clear();
			my votRequestGeneration ++;
		}
		my votNeedsRecalculation = true;
		my votValueMs.reset();
		my votResultStatus = U"stale";
		my votFailureReason = U"输入已改变；请重新提交分析。";
	}
	updateVotFormDisplay (form, me);
}

static void installVotFormCallbacks (UiForm form, SoundEditor me) {
	my votForm = form;
	GuiDialog_setOwnerWindow (form -> d_dialogForm, static_cast <GuiWindow> (my windowForm));
	for (integer i = 1; i <= form -> numberOfFields; i ++) {
		UiField field = form -> field [i].get();
		if (field -> text)
		{
			GuiText_setChangedCallback (field -> text, vot_gui_text_cb_changed, form);
		}
	}
}

static void applyVotResultJson (SoundEditor me, const std::string &resultJson) {
	if (resultJson.empty())
		return;
	const std::string status = votJsonStringField (resultJson, "status");
	autostring32 status32 = Melder_8to32_e (status.c_str());
	my votResultStatus = status32 ? status32.get() : U"failed";
	const std::string reason = votJsonStringField (resultJson, "failure_reason");
	autostring32 reason32 = Melder_8to32_e (reason.c_str());
	my votFailureReason = reason32 ? reason32.get() : U"";
	my votBurstTime.reset();
	my votVoicingTime.reset();
	my votValueMs.reset();
	const SampledXY audio = static_cast <SampledXY> (my data());
	const double burst = votJsonNumberField (resultJson, "burst_sample_index", -1.0);
	const double onset = votJsonNumberField (resultJson, "onset_sample_index", -1.0);
	const double vot = votJsonNumberField (resultJson, "vot_ms", undefined);
	if (burst >= 0.0 && onset >= 0.0) {
		my votBurstTime = editorTimeAtSample (audio, Melder_iround (burst));
		my votVoicingTime = editorTimeAtSample (audio, Melder_iround (onset));
	}
	if (isdefined (vot))
		my votValueMs = vot;
	my votValueIsCandidate = (status == "candidate");
	my votManualConfirmed = (status == "manual_confirmed");
	my votCalculationAttempted = true;
	my votNeedsRecalculation = false;
	my votProgressText = U"分析已完成";
	if (my votForm) {
		my votUpdatingForm = true;
		setVotFormBoundaries (my votForm, me);
		my votUpdatingForm = false;
	}
}

static void scheduleVotJobPoll (ThingHandle editorHandle, std::string jobId,
		integer generation)
{
	std::thread ([editorHandle, jobId = std::move (jobId), generation] () mutable {
		std::this_thread::sleep_for (std::chrono::milliseconds (180));
		Gui_addWorkProc ([editorHandle, jobId = std::move (jobId), generation] () mutable {
			SoundEditor me = static_cast <SoundEditor> (editorHandle.get());
			if (! me) {
				autostring32 staleJobId = Melder_8to32_e (jobId.c_str());
				PraatAiControl_cancelVOTJob (staleJobId.get());
				return;
			}
			if (my votRequestGeneration != generation || my votCurrentJobId != jobId)
				return;
			autostring32 nativeJobId = Melder_8to32_e (jobId.c_str());
			PraatAiVOTJobStatus status;
			try {
				status = PraatAiControl_pollVOTJob (nativeJobId.get());
			} catch (MelderError) {
				if (Melder_hasCrash())
					throw;
				setVotResultFailure (me, Melder_getError());
				Melder_clearError();
				my votCurrentJobId.clear();
				if (my votForm)
					updateVotFormDisplay (my votForm, me);
				return;
			} catch (const std::exception &error) {
				setVotResultFailure (me, Melder_peek8to32_u (error.what()));
				my votCurrentJobId.clear();
				if (my votForm)
					updateVotFormDisplay (my votForm, me);
				return;
			}
			if (status.state == "aligning" || status.state == "queued") {
				my votProgressText = status.stage == "aligning" ? U"分析进度：模型对齐中" : U"分析进度：等待后台任务";
				my votProgressText += U"（";
				my votProgressText += Melder_fixed (status.progress * 100.0, 0);
				my votProgressText += U"%）";
			} else if (status.state == "ready_for_acoustics") {
				my votProgressText = U"分析进度：原生声学边界检测中";
			} else if (status.state == "completed" || status.state == "failed") {
				if (! status.resultJson.empty())
					applyVotResultJson (me, status.resultJson);
				else
					setVotResultFailure (me, Melder_peek8to32_u (status.error.c_str()));
				my votCurrentJobId.clear();
			} else if (status.state == "cancelled") {
				my votResultStatus = U"stale";
				my votNeedsRecalculation = true;
				my votValueMs.reset();
				my votFailureReason = U"任务已取消，因为选区或音频已改变。";
				my votCurrentJobId.clear();
			}
			if (my votForm)
				updateVotFormDisplay (my votForm, me);
			if (! my votCurrentJobId.empty())
				scheduleVotJobPoll (editorHandle, jobId, generation);
		});
	}).detach();
}

static integer praatObjectIdForData (Thing data) {
	if (! theCurrentPraatObjects)
		return 0;
	for (integer object = 1; object <= theCurrentPraatObjects -> n; object ++)
		if (theCurrentPraatObjects -> list [object]. object == data)
			return theCurrentPraatObjects -> list [object]. id;
	return 0;
}

static void startVotEditorJob (SoundEditor me, double targetStartTime, double targetEndTime,
		double contextStartTime, double contextEndTime, conststring32 language,
		conststring32 transcript, conststring32 phonemes, integer targetPhoneIndex,
		integer mode, double burstThresholdDb, double pitchFloorHz)
{
	const SampledXY audio = static_cast <SampledXY> (my data());
	const integer objectId = praatObjectIdForData (my data());
	Melder_require (objectId > 0, U"VOT could not find the source Sound or LongSound object in the Praat object list.");
	const integer targetStartSample = editorSampleIndexAtTime (audio, targetStartTime);
	const integer targetEndSample = editorSampleIndexAtTime (audio, targetEndTime);
	const integer contextStartSample = editorSampleIndexAtTime (audio, contextStartTime);
	const integer contextEndSample = editorSampleIndexAtTime (audio, contextEndTime);
	Melder_require (targetStartSample >= contextStartSample && targetStartSample < targetEndSample &&
		targetEndSample <= contextEndSample,
		U"VOT target selection must be contained inside the fixed context window.");
	conststring32 modeName = mode == 1 ? U"model_assisted" : mode == 3 ? U"manual" : U"acoustic_only";
	std::optional<integer> manualBurstSample, manualOnsetSample;
	if (mode == 3) {
		Melder_require (my votBurstTime && my votVoicingTime,
			U"手动确认需要同时填写爆破释放时刻和起声时刻。");
		manualBurstSample = editorSampleIndexAtTime (audio, my votBurstTime.value());
		manualOnsetSample = editorSampleIndexAtTime (audio, my votVoicingTime.value());
	}
	PraatAiControl_noteEditorSelection (me, my data(), targetStartTime, targetEndTime,
		contextStartTime, contextEndTime);
	cancelVotEditorJob (me);
	const std::string jobId = PraatAiControl_submitVOTJob (
		my data(), objectId, targetStartSample, targetEndSample,
		contextStartSample, contextEndSample, modeName, language, transcript,
		phonemes, targetPhoneIndex, burstThresholdDb, pitchFloorHz,
		manualBurstSample, manualOnsetSample);
	my votCurrentJobId = jobId;
	my votRequestGeneration ++;
	my votResultStatus = U"aligning";
	my votProgressText = U"分析进度：已提交到后台";
	my votFailureReason.clear();
	my votValueMs.reset();
	my votBurstTime.reset();
	my votVoicingTime.reset();
	my votCalculationAttempted = false;
	my votNeedsRecalculation = false;
	my votValueIsCandidate = true;
	my votManualConfirmed = false;
	my votAnalysisStartTime = targetStartTime;
	my votAnalysisEndTime = targetEndTime;
	my votFixedContextStartTime = contextStartTime;
	my votFixedContextEndTime = contextEndTime;
	my votMode = mode;
	my votLanguage = language ? language : U"";
	my votTranscript = transcript ? transcript : U"";
	my votPhonemes = phonemes ? phonemes : U"";
	my votTargetPhoneIndex = targetPhoneIndex;
	my votBurstThresholdDb = burstThresholdDb;
	my votPitchFloorHz = pitchFloorHz;
	scheduleVotJobPoll (ThingHandle (me), jobId, my votRequestGeneration);
}

void structSoundEditor :: v1_dataChanged (Editor sender) {
	SoundEditor me = this;
	markVotResultStale (me, U"音频内容已改变；请重新提交分析。");
	PraatAiControl_clearEditorVOTContext (me, my data());
	my votFixedContextStartTime.reset();
	my votFixedContextEndTime.reset();
	SoundEditor_Parent :: v1_dataChanged (sender);
	Thing_cast (SampledXY, soundOrLongSound, our data());
	our soundArea() -> functionChanged (soundOrLongSound);
	our soundAnalysisArea() -> functionChanged (soundOrLongSound);
	if (my votForm)
		updateVotFormDisplay (my votForm, this);
}

void structSoundEditor :: v_updateText () {
	SoundEditor me = this;
	SoundEditor_Parent :: v_updateText ();
	if (my votStateHasSelection && (my startSelection != my votStateSelectionStart ||
		my endSelection != my votStateSelectionEnd))
	{
		markVotResultStale (me, U"选区已改变；请重新提交分析。固定上下文会在目标移出范围后重设。");
		const SampledXY audio = static_cast <SampledXY> (my data());
		const integer targetStart = editorSampleIndexAtTime (audio, my startSelection);
		const integer targetEnd = editorSampleIndexAtTime (audio, my endSelection);
		my votAnalysisStartTime = my startSelection;
		my votAnalysisEndTime = my endSelection;
		if (targetStart >= 0 && targetEnd > targetStart &&
			(my votFixedContextStartTime && my votFixedContextEndTime) &&
			(targetStart < editorSampleIndexAtTime (audio, my votFixedContextStartTime.value()) ||
			 targetEnd > editorSampleIndexAtTime (audio, my votFixedContextEndTime.value())))
		{
			const double domainStart = audio -> x1 - 0.5 * audio -> dx;
			const double domainEnd = audio -> x1 + (audio -> nx - 0.5) * audio -> dx;
			my votFixedContextStartTime = std::max (domainStart, my startSelection - 0.5);
			my votFixedContextEndTime = std::min (domainEnd, my endSelection + 0.5);
		}
		my votStateSelectionStart = my startSelection;
		my votStateSelectionEnd = my endSelection;
		if (my votForm) {
			my votUpdatingForm = true;
			setVotFormRealAtIndex (my votForm, 1, my votAnalysisStartTime.value());
			setVotFormRealAtIndex (my votForm, 2, my votAnalysisEndTime.value());
			if (my votFixedContextStartTime && my votFixedContextEndTime) {
				setVotFormRealAtIndex (my votForm, VOT_FORM_CONTEXT_START_FIELD_INDEX, my votFixedContextStartTime.value());
				setVotFormRealAtIndex (my votForm, VOT_FORM_CONTEXT_END_FIELD_INDEX, my votFixedContextEndTime.value());
			}
			updateVotFormDisplay (my votForm, me);
			my votUpdatingForm = false;
		}
		PraatAiControl_noteEditorSelection (me, my data(), my startSelection, my endSelection,
			my votFixedContextStartTime, my votFixedContextEndTime);
	}
}

static void menu_cb_SoundEditor_VOT (SoundEditor me, EDITOR_ARGS) {
	EDITOR_FORM (U"VOT analysis", U"VOT...")
		REAL_OR_UNDEFINED (startTime, U"Start time (s)", U"undefined")
		REAL_OR_UNDEFINED (endTime, U"End time (s)", U"undefined")
		REAL_OR_UNDEFINED (burstTime, U"Burst/release time (s)", U"undefined")
		REAL_OR_UNDEFINED (voicingTime, U"Voicing onset time (s)", U"undefined")
		MUTABLE_COMMENT (votValueText, U"VOT 值（ms）：尚未计算")
		MUTABLE_COMMENT (progressText, U"分析进度：尚未开始")
		CHOICE (mode, U"分析模式", 1)
			OPTION (U"模型辅助自动")
			OPTION (U"纯声学候选")
			OPTION (U"人工确认")
		REAL_OR_UNDEFINED (contextStartTime, U"固定上下文开始时间（s）", U"undefined")
		REAL_OR_UNDEFINED (contextEndTime, U"固定上下文结束时间（s）", U"undefined")
		WORD (language, U"语言代码", U"")
		SENTENCE (transcript, U"完整语句文字", U"")
		TEXTFIELD (phonemes, U"完整语句音素（空格分隔）", U"", 2)
		NATURAL0 (targetPhoneIndex, U"目标音素序号（从 0 开始）", U"0")
		REAL (burstThresholdDb, U"Minimum burst rise (dB)", U"6.0")
		REAL (pitchFloorHz, U"Pitch floor (Hz)", U"75.0")
	EDITOR_OK
		const bool hasSelection = my startSelection < my endSelection;
		if (! hasSelection)
			Melder_throw (U"请先选择目标片段；不会将整段录音作为 VOT。");
		const SampledXY audio = static_cast <SampledXY> (my data());
		const double selectedStart = my startSelection;
		const double selectedEnd = my endSelection;
		const bool sameSelection = my votStateHasSelection &&
			my votStateSelectionStart == selectedStart && my votStateSelectionEnd == selectedEnd;
		if (! sameSelection) {
			cancelVotEditorJob (me);
			my votStateHasSelection = true;
			my votStateSelectionStart = selectedStart;
			my votStateSelectionEnd = selectedEnd;
			my votBurstTime.reset();
			my votVoicingTime.reset();
			my votValueMs.reset();
			my votCalculationAttempted = false;
			my votNeedsRecalculation = true;
			my votManualConfirmed = false;
			my votValueIsCandidate = false;
			const double domainStart = audio -> x1 - 0.5 * audio -> dx;
			const double domainEnd = audio -> x1 + (audio -> nx - 0.5) * audio -> dx;
			my votFixedContextStartTime = std::max (domainStart, selectedStart - 0.5);
			my votFixedContextEndTime = std::min (domainEnd, selectedEnd + 0.5);
		}
		if (! my votFixedContextStartTime || ! my votFixedContextEndTime) {
			const double domainStart = audio -> x1 - 0.5 * audio -> dx;
			const double domainEnd = audio -> x1 + (audio -> nx - 0.5) * audio -> dx;
			my votFixedContextStartTime = std::max (domainStart, selectedStart - 0.5);
			my votFixedContextEndTime = std::min (domainEnd, selectedEnd + 0.5);
		}
		PraatAiControl_noteEditorSelection (me, my data(), selectedStart, selectedEnd,
			my votFixedContextStartTime, my votFixedContextEndTime);
		if (my votResultStatus == U"stale" && my votCurrentJobId.empty())
			my votFailureReason = U"选区或输入已改变；点击应用以重新分析。";
		startTime = my votAnalysisStartTime.value_or (selectedStart);
		endTime = my votAnalysisEndTime.value_or (selectedEnd);
		burstTime = my votBurstTime.value_or (undefined);
		voicingTime = my votVoicingTime.value_or (undefined);
		mode = my votMode;
		contextStartTime = my votFixedContextStartTime.value();
		contextEndTime = my votFixedContextEndTime.value();
		language = my votLanguage.empty() ? U"" : my votLanguage.c_str();
		transcript = my votTranscript.empty() ? U"" : my votTranscript.c_str();
		phonemes = my votPhonemes.empty() ? U"" : my votPhonemes.c_str();
		targetPhoneIndex = my votTargetPhoneIndex;
		burstThresholdDb = my votBurstThresholdDb;
		pitchFloorHz = my votPitchFloorHz;
		my votUpdatingForm = true;
		SET_REAL (startTime, my votAnalysisStartTime.value_or (selectedStart))
		SET_REAL (endTime, my votAnalysisEndTime.value_or (selectedEnd))
		SET_REAL (burstTime, my votBurstTime.value_or (undefined))
		SET_REAL (voicingTime, my votVoicingTime.value_or (undefined))
		SET_OPTION (mode, my votMode)
		SET_REAL (contextStartTime, my votFixedContextStartTime.value())
		SET_REAL (contextEndTime, my votFixedContextEndTime.value())
		SET_STRING (language, my votLanguage.empty() ? U"" : my votLanguage.c_str())
		SET_STRING (transcript, my votTranscript.empty() ? U"" : my votTranscript.c_str())
		SET_STRING (phonemes, my votPhonemes.empty() ? U"" : my votPhonemes.c_str())
		SET_INTEGER (targetPhoneIndex, my votTargetPhoneIndex)
		SET_REAL (burstThresholdDb, my votBurstThresholdDb)
		SET_REAL (pitchFloorHz, my votPitchFloorHz)
		SET_REAL (burstTime, my votBurstTime.value_or (undefined))
		SET_REAL (voicingTime, my votVoicingTime.value_or (undefined))
		updateVotFormDisplay (cmd -> d_uiform.get(), me);
		my votUpdatingForm = false;
		installVotFormCallbacks (cmd -> d_uiform.get(), me);
	EDITOR_DO
		try {
			const SampledXY audio = static_cast <SampledXY> (my data());
			const integer selectedStartSample = editorSampleIndexAtTime (audio, startTime);
			const integer selectedEndSample = editorSampleIndexAtTime (audio, endTime);
			if (selectedStartSample < 0 || selectedEndSample <= selectedStartSample)
				Melder_throw (U"请先选择非空目标片段；不会退回整段音频。");
			const integer contextStartSample = editorSampleIndexAtTime (audio, contextStartTime);
			const integer contextEndSample = editorSampleIndexAtTime (audio, contextEndTime);
			if (targetPhoneIndex < 0)
				Melder_throw (U"目标音素序号必须从 0 开始并填写非负整数。");
			my votAnalysisStartTime = editorSelectionTimeAtSample (audio, selectedStartSample);
			my votAnalysisEndTime = editorSelectionTimeAtSample (audio, selectedEndSample);
			my votBurstTime = editorOptionalVotBoundary (burstTime);
			my votVoicingTime = editorOptionalVotBoundary (voicingTime);
			my votFixedContextStartTime = editorSelectionTimeAtSample (audio, contextStartSample);
			my votFixedContextEndTime = editorSelectionTimeAtSample (audio, contextEndSample);
			my votMode = mode;
			my votLanguage = language ? language : U"";
			my votTranscript = transcript ? transcript : U"";
			my votPhonemes = phonemes ? phonemes : U"";
			my votTargetPhoneIndex = targetPhoneIndex;
			my votBurstThresholdDb = burstThresholdDb;
			my votPitchFloorHz = pitchFloorHz;
			if (mode == 3 && (! my votBurstTime || ! my votVoicingTime))
				Melder_throw (U"人工确认模式需要同时填写爆破释放时刻和起声时刻。");
			startVotEditorJob (me, my votAnalysisStartTime.value(), my votAnalysisEndTime.value(),
				my votFixedContextStartTime.value(), my votFixedContextEndTime.value(),
				language, transcript, phonemes, targetPhoneIndex, mode, burstThresholdDb, pitchFloorHz);
			if (_sendingForm_)
				updateVotFormDisplay (_sendingForm_, me);
		} catch (MelderError) {
			if (Melder_hasCrash())
				throw;
			PraatAiControl_reportVOTEditorDiagnostic (Melder_getError());
			setVotResultFailure (me, Melder_getError());
			Melder_clearError();
			if (_sendingForm_)
				updateVotFormDisplay (_sendingForm_, me);
		} catch (const std::exception &error) {
			conststring32 reason = Melder_peek8to32_u (error.what());
			PraatAiControl_reportVOTEditorDiagnostic (reason);
			setVotResultFailure (me, reason);
			if (_sendingForm_)
				updateVotFormDisplay (_sendingForm_, me);
		}
	EDITOR_END
}

static void menu_cb_SoundEditor_VOTMenu (SoundEditor me, EDITOR_ARGS) {
	Editor_doMenuCommand (me, U"VOT...", 0, nullptr, nullptr, nullptr);
}

void structSoundEditor :: v_createMenusAfterFunctionAreas () {
	EditorMenu votMenu = Editor_addMenu (this, U"VOT", 0);
	EditorMenu_addCommand (votMenu, U"VOT...", 0, menu_cb_SoundEditor_VOTMenu);
}

void structSoundEditor :: v_createMenus () {
	SoundEditor_Parent :: v_createMenus ();
	EditorMenu_addCommand (editMenu, U"VOT...", GuiMenu_HIDDEN, menu_cb_SoundEditor_VOT);
}

void structSoundEditor :: v_createMenuItems_help (EditorMenu menu) {
	structFunctionEditor :: v_createMenuItems_help (menu);
	EditorMenu_addCommand (menu, U"SoundEditor help", '?', menu_cb_SoundEditorHelp);
	EditorMenu_addCommand (menu, U"LongSoundEditor help", 0, menu_cb_LongSoundEditorHelp);
	// BUG: add help on Sound area and Sound analysis area
}

autoSoundEditor SoundEditor_create (conststring32 title, SampledXY soundOrLongSound) {
	Melder_assert (soundOrLongSound);
	Melder_assert (soundOrLongSound -> ny > 0);
	try {
		autoSoundEditor me = Thing_new (SoundEditor);
		if (Thing_isa (soundOrLongSound, classSound))
			my soundArea() = SoundArea_create (true, nullptr, me.get());
		else
			my soundArea() = LongSoundArea_create (false, nullptr, me.get());
		my soundAnalysisArea() = SoundAnalysisArea_create (false, nullptr, me.get());
		FunctionEditor_init (me.get(), title, soundOrLongSound);
		return me;
	} catch (MelderError) {
		Melder_throw (U"Sound window not created.");
	}
}

/* End of file SoundEditor.cpp */
