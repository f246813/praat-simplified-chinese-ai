#include "SegmentAcousticEditor.h"

#include "Sound_and_Spectrogram.h"
#include "Spectrogram.h"
#include "EditorM.h"
#include "praat.h"
#include "melder_files.h"

#include <algorithm>
#include <cmath>
#include <exception>
#include <limits>
#include <memory>
#include <vector>

Thing_implement (SegmentAcousticEditor, Editor, 0);

namespace {

struct SegmentSourceData {
	autoSound sound;
	autoLongSound longSound;
	SourceIdentity identity;
	double xmin { 0.0 }, xmax { 0.0 };
	double sampleRate { 0.0 };
	integer channels { 0 };
};

struct SegmentSourceChoice {
	std::optional<integer> objectId;
	std::shared_ptr<SegmentSourceData> fileSource;
	std::u32string name;
};

struct SegmentEditorState {
	GuiOptionMenu sourceMenu [2] { nullptr, nullptr };
	GuiOptionMenu analysisMenu [2] { nullptr, nullptr };
	GuiText startField [2] { nullptr, nullptr };
	GuiText endField [2] { nullptr, nullptr };
	GuiText boundaryBurstField [2] { nullptr, nullptr };
	GuiText boundaryVoicingField [2] { nullptr, nullptr };
	GuiLabel sourceStatus [2] { nullptr, nullptr };
	GuiLabel previewStatus [2] { nullptr, nullptr };
	GuiLabel comparisonSummary { nullptr };
	GuiDrawingArea waveformArea [2] { nullptr, nullptr };
	GuiDrawingArea spectrogramArea [2] { nullptr, nullptr };
	GuiDrawingArea comparisonPlotArea { nullptr };
	GuiDrawingArea frequencyPlotArea { nullptr };
	autoGraphics waveformGraphics [2];
	autoGraphics spectrogramGraphics [2];
	autoGraphics comparisonPlotGraphics;
	autoGraphics frequencyPlotGraphics;
	std::optional<AnalysisResult> analyses [2];
	std::optional<AnalysisResult> candidateAnalyses [2];
	std::optional<ComparisonResult> comparison;
	std::vector<FrequencyOverlay> frequencyOverlays;
	std::vector <SegmentSourceChoice> choices [2];
	std::shared_ptr <SegmentSourceData> activeSource [2];
	SegmentAnalysisSelection initialTarget;
	std::u32string initialName;
	std::optional<integer> initialObjectId;
};

SegmentEditorState *state (SegmentAcousticEditor me) {
	return static_cast<SegmentEditorState *> (my d_privateState);
}

SegmentAnalysisSelection &selectionFor (SegmentAcousticEditor me, integer side) {
	if (side == 0)
		return my selection.target;
	Melder_assert (my selection.reference);
	return my selection.reference.value();
}

void invalidateComparison (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	editorState -> analyses [side].reset();
	editorState -> candidateAnalyses [side].reset();
	if (editorState -> boundaryBurstField [side])
		GuiText_setString (editorState -> boundaryBurstField [side], U"");
	if (editorState -> boundaryVoicingField [side])
		GuiText_setString (editorState -> boundaryVoicingField [side], U"");
	editorState -> comparison.reset();
	editorState -> frequencyOverlays.clear();
	if (editorState -> comparisonSummary)
		GuiLabel_setText (editorState -> comparisonSummary, U"来源或范围已更改。请重新估计 VOT 候选，或输入两侧边界后确认比较。");
	if (editorState -> comparisonPlotGraphics)
		Graphics_updateWs (editorState -> comparisonPlotGraphics.get());
	if (editorState -> frequencyPlotGraphics)
		Graphics_updateWs (editorState -> frequencyPlotGraphics.get());
}

void setStatus (SegmentAcousticEditor me, integer side, conststring32 message) {
	GuiLabel_setText (state (me) -> sourceStatus [side], message);
}

void setCallbackError (SegmentAcousticEditor me, integer side, conststring32 prefix) {
	conststring32 error = Melder_getError();
	GuiLabel_setText (state (me) -> sourceStatus [side], Melder_cat (prefix, U"：", error));
	Melder_clearError ();
}

template <typename F> void safelyDo (SegmentAcousticEditor me, integer side, conststring32 prefix, F && action) {
	try {
		action ();
	} catch (MelderError) {
		setCallbackError (me, side, prefix);
	} catch (const std::exception &error) {
		GuiLabel_setText (state (me) -> sourceStatus [side],
			Melder_cat (prefix, U"：", Melder_peek8to32_u (error.what())));
		Melder_clearError ();
	} catch (...) {
		GuiLabel_setText (state (me) -> sourceStatus [side], Melder_cat (prefix, U"：未知错误"));
		Melder_clearError ();
	}
}

std::shared_ptr<SegmentSourceData> copyPraatSource (Daata object, std::optional<integer> objectId,
		conststring32 displayName) {
	auto result = std::make_shared<SegmentSourceData>();
	if (Thing_isa (object, classSound)) {
		result -> sound = Data_copy ((Sound) object);
		result -> xmin = result -> sound -> xmin;
		result -> xmax = result -> sound -> xmax;
		result -> channels = result -> sound -> ny;
		result -> sampleRate = 1.0 / result -> sound -> dx;
		result -> identity.kind = SourceKind::sound;
	} else if (Thing_isa (object, classLongSound)) {
		result -> longSound = Data_copy ((LongSound) object);
		result -> xmin = result -> longSound -> xmin;
		result -> xmax = result -> longSound -> xmax;
		result -> channels = result -> longSound -> numberOfChannels;
		result -> sampleRate = result -> longSound -> sampleRate;
		result -> identity.kind = SourceKind::longSound;
	} else {
		Melder_throw (U"The selected object is not a Sound or LongSound.");
	}
	result -> identity.objectId = objectId;
	result -> identity.displayName = displayName ? displayName : U"audio source";
	result -> identity.channels = result -> channels;
	result -> identity.sampleRate = result -> sampleRate;
	return result;
}

bool hasObjectChoice (SegmentEditorState *editorState, integer side, integer objectId) {
	for (const SegmentSourceChoice &choice : editorState -> choices [side])
		if (choice.objectId && choice.objectId.value() == objectId)
			return true;
	return false;
}

void refreshObjectChoices (SegmentAcousticEditor me) {
	SegmentEditorState *editorState = state (me);
	if (! theCurrentPraatObjects)
		return;
	for (integer iobject = 1; iobject <= theCurrentPraatObjects -> n; iobject ++) {
		const structPraat_Object &entry = theCurrentPraatObjects -> list [iobject];
		if (! entry.object || entry.isBeingCreated || (! Thing_isa (entry.object, classSound) && ! Thing_isa (entry.object, classLongSound)))
			continue;
		for (integer side = 0; side < 2; side ++) {
			if (hasObjectChoice (editorState, side, entry.id))
				continue;
			SegmentSourceChoice choice;
			choice.objectId = entry.id;
			choice.name = entry.name.get();
			editorState -> choices [side]. push_back (choice);
			GuiOptionMenu_addOption (editorState -> sourceMenu [side], choice.name.c_str());
		}
	}
}

void appendFileChoice (SegmentAcousticEditor me, integer side, const std::shared_ptr<SegmentSourceData> &source) {
	SegmentEditorState *editorState = state (me);
	SegmentSourceChoice choice;
	choice.fileSource = source;
	choice.name = source -> identity.displayName;
	editorState -> choices [side]. push_back (choice);
	GuiOptionMenu_addOption (editorState -> sourceMenu [side], choice.name.c_str());
	GuiOptionMenu_setValue (editorState -> sourceMenu [side], (int) editorState -> choices [side].size());
}

void syncSourceIdentity (SegmentAcousticEditor me, integer side, bool clearRange) {
	SegmentEditorState *editorState = state (me);
	if (clearRange)
		invalidateComparison (me, side);
	const std::shared_ptr<SegmentSourceData> source = editorState -> activeSource [side];
	if (side == 1 && ! my selection.reference)
		my selection.reference = SegmentAnalysisSelection {};
	SegmentAnalysisSelection &current = selectionFor (me, side);
	if (! source) {
		if (side == 1)
			TargetReferenceSegment_clearReference (& my selection);
			return;
	}
	current.metadata.source = source -> identity;
	if (side == 0)
		TargetReferenceSegment_setTarget (& my selection, current);
	else
		TargetReferenceSegment_setReference (& my selection, current);
	if (clearRange) {
		current.metadata.startTime = undefined;
		current.metadata.endTime = undefined;
		current.playbackStartTime = undefined;
		current.playbackEndTime = undefined;
		GuiText_setString (editorState -> startField [side], U"");
		GuiText_setString (editorState -> endField [side], U"");
	}
	GuiLabel_setText (editorState -> sourceStatus [side], Melder_cat (
		source -> identity.displayName.c_str(), U"；", source -> channels, U" 通道，",
		Melder_single (source -> sampleRate), U" Hz；范围 ", Melder_single (source -> xmin), U"–", Melder_single (source -> xmax), U" 秒"
	));
	GuiThing_show (editorState -> waveformArea [side]);
	GuiThing_show (editorState -> spectrogramArea [side]);
	GuiThing_show (editorState -> sourceStatus [side]);
	if (editorState -> waveformGraphics [side])
		Graphics_updateWs (editorState -> waveformGraphics [side].get());
	if (editorState -> spectrogramGraphics [side])
		Graphics_updateWs (editorState -> spectrogramGraphics [side].get());
}

void installObjectChoice (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	const int selected = GuiOptionMenu_getValue (editorState -> sourceMenu [side]);
	Melder_require (selected >= 1 && selected <= (int) editorState -> choices [side].size(), U"请选择有效的 Sound 或 LongSound 来源。");
	const SegmentSourceChoice &choice = editorState -> choices [side] [selected - 1];
	if (choice.fileSource) {
		editorState -> activeSource [side] = choice.fileSource;
	} else if (choice.objectId) {
		Daata object = nullptr;
		if (theCurrentPraatObjects) {
			for (integer iobject = 1; iobject <= theCurrentPraatObjects -> n; iobject ++)
				if (theCurrentPraatObjects -> list [iobject].id == choice.objectId.value()) {
					object = theCurrentPraatObjects -> list [iobject].object;
					break;
				}
		}
		Melder_require (object, U"来源对象已从 Praat 对象列表中移除，请刷新并重新选择。");
		editorState -> activeSource [side] = copyPraatSource (object, choice.objectId, choice.name.c_str());
	} else {
		editorState -> activeSource [side].reset();
	}
	syncSourceIdentity (me, side, true);
	if (editorState -> activeSource [side])
		GuiLabel_setText (editorState -> sourceStatus [side], U"来源已更换。请在此侧单独输入并应用片段范围。");
}

void loadFiles (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	autoStringSet files = GuiFileSelect_getInfileNames (my windowForm, U"从文件夹读取音频文件（可多选）", true);
	for (integer ifile = 1; ifile <= files -> size; ifile ++) {
		conststring32 path = files -> at [ifile] -> string.get();
		structMelderFile file {};
		Melder_pathToFile (path, & file);
		autoLongSound longSound = LongSound_open (& file);
		const long double memoryBytes = (long double) longSound -> nx * longSound -> numberOfChannels * sizeof (double);
		auto source = std::make_shared<SegmentSourceData>();
		source -> xmin = longSound -> xmin;
		source -> xmax = longSound -> xmax;
		source -> sampleRate = longSound -> sampleRate;
		source -> channels = longSound -> numberOfChannels;
		source -> identity.kind = memoryBytes <= 64.0L * 1024.0L * 1024.0L ? SourceKind::sound : SourceKind::longSound;
		source -> identity.displayName = path;
		source -> identity.filePath = std::u32string (path);
		source -> identity.channels = source -> channels;
		source -> identity.sampleRate = source -> sampleRate;
		if (source -> identity.kind == SourceKind::sound)
			source -> sound = Sound_readFromSoundFile (& file);
		else
			source -> longSound = longSound.move();
		appendFileChoice (me, side, source);
		editorState -> activeSource [side] = source;
		syncSourceIdentity (me, side, true);
	}
	if (files -> size == 0)
		setStatus (me, side, U"未加载来源；可以从对象列表选择 Sound/LongSound 或从文件夹读取。");
}

bool readRange (SegmentAcousticEditor me, integer side, double *start, double *end) {
	autostring32 startText = GuiText_getString (state (me) -> startField [side]);
	autostring32 endText = GuiText_getString (state (me) -> endField [side]);
	if (! startText || ! endText || startText [0] == U'\0' || endText [0] == U'\0')
		return false;
	*start = Melder_atof (startText.get());
	*end = Melder_atof (endText.get());
	return true;
}

bool readVotBoundaries (SegmentAcousticEditor me, integer side, double *burst, double *voicing) {
	autostring32 burstText = GuiText_getString (state (me) -> boundaryBurstField [side]);
	autostring32 voicingText = GuiText_getString (state (me) -> boundaryVoicingField [side]);
	if (! burstText || ! voicingText || burstText [0] == U'\0' || voicingText [0] == U'\0')
		return false;
	*burst = Melder_atof (burstText.get());
	*voicing = Melder_atof (voicingText.get());
	return std::isfinite (*burst) && std::isfinite (*voicing);
}

void applyRange (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	const std::shared_ptr<SegmentSourceData> source = editorState -> activeSource [side];
	Melder_require (source, U"请先为此侧选择或加载一个 Sound/LongSound 来源。");
	double start = 0.0, end = 0.0;
	Melder_require (readRange (me, side, & start, & end), U"请输入此侧的起始和结束时间；不会自动把整个文件当作片段。");
	Melder_require (std::isfinite (start) && std::isfinite (end) && start < end && start >= source -> xmin && end <= source -> xmax,
		U"时间范围必须满足 来源起点 ≤ 开始时间 < 结束时间 ≤ 来源终点。");
	SegmentAnalysisSelection &current = selectionFor (me, side);
	current.metadata.startTime = start;
	current.metadata.endTime = end;
	current.playbackStartTime = start;
	current.playbackEndTime = end;
	switch (GuiOptionMenu_getValue (editorState -> analysisMenu [side])) {
		case 1: current.analysisKind = AnalysisKind::VowelNasality; break;
		case 2: current.analysisKind = AnalysisKind::NasalConsonant; break;
		case 3: current.analysisKind = AnalysisKind::RSegment; break;
		default: current.analysisKind = AnalysisKind::VOT; break;
	}
	if (side == 0)
		TargetReferenceSegment_setTarget (& my selection, current);
	else
		TargetReferenceSegment_setReference (& my selection, current);
	invalidateComparison (me, side);
	setStatus (me, side, Melder_cat (U"范围已应用：", Melder_single (start), U"–", Melder_single (end), U" 秒；分析类型：",
		current.analysisKind == AnalysisKind::VOT ? U"VOT" : current.analysisKind == AnalysisKind::RSegment ? U"R 音" :
		current.analysisKind == AnalysisKind::NasalConsonant ? U"鼻音辅音" : U"元音鼻化"));
	Graphics_updateWs (editorState -> waveformGraphics [side].get());
	Graphics_updateWs (editorState -> spectrogramGraphics [side].get());
}

autoSound extractPreview (const SegmentSourceData &source, double start, double end) {
	if (source.sound)
		return Sound_extractPart (source.sound.get(), start, end, kSound_windowShape::RECTANGULAR, 1.0, true);
	return LongSound_extractPart (source.longSound.get(), start, end, true);
}

void renderPreview (SegmentAcousticEditor me, integer side, bool spectrogram) {
	SegmentEditorState *editorState = state (me);
	Graphics graphics = spectrogram ? editorState -> spectrogramGraphics [side].get() : editorState -> waveformGraphics [side].get();
	Graphics_clearWs (graphics);
	const std::shared_ptr<SegmentSourceData> source = editorState -> activeSource [side];
	if (! source) {
		Graphics_setWindow (graphics, 0.0, 1.0, 0.0, 1.0);
		Graphics_text (graphics, 0.5, 0.5, U"选择音频来源以显示预览");
		return;
	}
	double start = source -> xmin, end = source -> xmax;
	if (! readRange (me, side, & start, & end) || ! (start < end && start >= source -> xmin && end <= source -> xmax)) {
		start = source -> xmin;
		end = std::min (source -> xmax, source -> xmin + 0.75);
	}
	autoSound preview = extractPreview (*source, start, end);
	if (! spectrogram) {
		Graphics_setViewport (graphics, 50.0, GuiControl_getWidth (spectrogram ? editorState -> spectrogramArea [side] : editorState -> waveformArea [side]) - 8.0,
			12.0, GuiControl_getHeight (editorState -> waveformArea [side]) - 26.0);
		Graphics_setWindow (graphics, start, end, -1.0, 1.0);
		Sound_draw (preview.get(), graphics, start, end, 0.0, 0.0, true, U"curve");
		if (editorState -> analyses [side]) {
			const AnalysisResult &analysis = editorState -> analyses [side].value();
			for (const MetricResult &metric : analysis.metrics) {
				const bool candidateBoundary = metric.id == U"burst_time_candidate" || metric.id == U"voicing_time_candidate";
				const bool confirmedBoundary = metric.id == U"burst_time_confirmed" || metric.id == U"voicing_time_confirmed";
				if (! metric.value || (! candidateBoundary && ! confirmedBoundary))
					continue;
				const double time = metric.value.value();
				if (time < start || time > end)
					continue;
				const bool isBurst = metric.id == U"burst_time_candidate" || metric.id == U"burst_time_confirmed";
				Graphics_setColour (graphics, confirmedBoundary ? Melder_GREEN : isBurst ? Melder_RED : Melder_BLUE);
				Graphics_line (graphics, time, -1.0, time, 1.0);
				Graphics_text (graphics, time, isBurst ? 0.85 : 0.70,
					confirmedBoundary ? (isBurst ? U"burst confirmed" : U"voicing confirmed") :
						(isBurst ? U"burst candidate" : U"voicing candidate"));
			}
			Graphics_setColour (graphics, Melder_BLACK);
		}
	} else {
		const double topFrequency = std::min (8000.0, 0.5 / preview -> dx);
		Melder_require (topFrequency > 0.0, U"采样率不足以绘制频谱预览。");
		autoSpectrogram image = Sound_to_Spectrogram_e (preview.get(), 0.005, topFrequency, 0.002, 100.0,
			kSound_to_Spectrogram_windowShape::HANNING, 8.0, 8.0);
		Graphics_setViewport (graphics, 50.0, GuiControl_getWidth (editorState -> spectrogramArea [side]) - 8.0,
			12.0, GuiControl_getHeight (editorState -> spectrogramArea [side]) - 26.0);
		Graphics_setWindow (graphics, start, end, 0.0, topFrequency);
		Spectrogram_paintInside (image.get(), graphics, start, end, 0.0, topFrequency, 0.0, true,
			50.0, 6.0, 0.0, kSpectrogram_colourMap::GREY, false);
	}
}

void exposeWaveform (SegmentAcousticEditor me, GuiDrawingArea_ExposeEvent event) {
	const integer side = event -> widget == state (me) -> waveformArea [0] ? 0 : 1;
	try {
		renderPreview (me, side, false);
		GuiLabel_setText (state (me) -> previewStatus [side], U"");
	} catch (MelderError) {
		GuiLabel_setText (state (me) -> previewStatus [side], Melder_cat (U"波形预览失败：", Melder_getError()));
		Melder_clearError ();
	} catch (const std::exception &error) {
		GuiLabel_setText (state (me) -> previewStatus [side], Melder_cat (U"波形预览失败：", Melder_peek8to32_u (error.what())));
		Melder_clearError ();
	} catch (...) {
		GuiLabel_setText (state (me) -> previewStatus [side], U"波形预览失败：未知错误");
		Melder_clearError ();
	}
}

void exposeSpectrogram (SegmentAcousticEditor me, GuiDrawingArea_ExposeEvent event) {
	const integer side = event -> widget == state (me) -> spectrogramArea [0] ? 0 : 1;
	try {
		renderPreview (me, side, true);
		GuiLabel_setText (state (me) -> previewStatus [side], U"");
	} catch (MelderError) {
		GuiLabel_setText (state (me) -> previewStatus [side], Melder_cat (U"频谱预览失败：", Melder_getError()));
		Melder_clearError ();
	} catch (const std::exception &error) {
		GuiLabel_setText (state (me) -> previewStatus [side], Melder_cat (U"频谱预览失败：", Melder_peek8to32_u (error.what())));
		Melder_clearError ();
	} catch (...) {
		GuiLabel_setText (state (me) -> previewStatus [side], U"频谱预览失败：未知错误");
		Melder_clearError ();
	}
}

const MetricResult *findResultMetric (const AnalysisResult &analysis, const std::u32string &id) {
	for (const MetricResult &metric : analysis.metrics)
		if (metric.id == id)
			return & metric;
	return nullptr;
}

conststring32 editorMetricStatusName (MetricStatus status) {
	switch (status) {
		case MetricStatus::measured: return U"已测量";
		case MetricStatus::warning: return U"需复核";
		case MetricStatus::unavailable: return U"不可用";
	}
	return U"不可用";
}

void renderComparisonPlot (SegmentAcousticEditor me) {
	SegmentEditorState *editorState = state (me);
	Graphics graphics = editorState -> comparisonPlotGraphics.get();
	Graphics_clearWs (graphics);
	Graphics_setViewport (graphics, 42.0, GuiControl_getWidth (editorState -> comparisonPlotArea) - 12.0,
		12.0, GuiControl_getHeight (editorState -> comparisonPlotArea) - 28.0);
	if (! editorState -> analyses [0] || ! editorState -> analyses [1]) {
		Graphics_setWindow (graphics, 0.0, 100.0, 0.0, 1.0);
		Graphics_text (graphics, 50.0, 0.5, U"完成两侧分析后显示相对时长曲线叠图");
		return;
	}
	const AnalysisResult &target = editorState -> analyses [0].value();
	const AnalysisResult &reference = editorState -> analyses [1].value();
	struct OverlayPair { NormalizedTimeSeries target, reference; };
	std::vector<OverlayPair> overlays;
	double minimumValue = std::numeric_limits<double>::infinity();
	double maximumValue = - std::numeric_limits<double>::infinity();
	for (const TimeSeries &targetCurve : target.curves) {
		for (const TimeSeries &referenceCurve : reference.curves) {
			if (targetCurve.metricId != referenceCurve.metricId || targetCurve.unit != referenceCurve.unit)
				continue;
			OverlayPair pair {
				normalizeTimeSeriesForOverlay (targetCurve, target.source),
				normalizeTimeSeriesForOverlay (referenceCurve, reference.source)
			};
			for (const double value : pair.target.values) {
				minimumValue = std::min (minimumValue, value);
				maximumValue = std::max (maximumValue, value);
			}
			for (const double value : pair.reference.values) {
				minimumValue = std::min (minimumValue, value);
				maximumValue = std::max (maximumValue, value);
			}
			overlays.push_back (std::move (pair));
			break;
		}
	}
	if (overlays.empty()) {
		Graphics_setWindow (graphics, 0.0, 100.0, 0.0, 1.0);
		Graphics_text (graphics, 50.0, 0.5, U"当前分析没有两侧共有的连续时间曲线");
		return;
	}
	if (maximumValue <= minimumValue) {
		minimumValue -= 1.0;
		maximumValue += 1.0;
	} else {
		const double margin = (maximumValue - minimumValue) * 0.05;
		minimumValue -= margin;
		maximumValue += margin;
	}
	Graphics_setWindow (graphics, 0.0, 100.0, minimumValue, maximumValue);
	Graphics_drawInnerBox (graphics);
	for (const OverlayPair &pair : overlays) {
		for (size_t index = 1; index < pair.target.values.size(); index ++) {
			Graphics_setColour (graphics, Melder_BLUE);
			Graphics_line (graphics, pair.target.relativePercent [index - 1], pair.target.values [index - 1],
				pair.target.relativePercent [index], pair.target.values [index]);
		}
		for (size_t index = 1; index < pair.reference.values.size(); index ++) {
			Graphics_setColour (graphics, Melder_RED);
			Graphics_line (graphics, pair.reference.relativePercent [index - 1], pair.reference.values [index - 1],
				pair.reference.relativePercent [index], pair.reference.values [index]);
		}
	}
	Graphics_setColour (graphics, Melder_BLUE);
	Graphics_text (graphics, 2.0, maximumValue, Melder_cat (U"目标：", target.source.source.displayName.c_str(), U" [",
		Melder_single (target.source.startTime), U"–", Melder_single (target.source.endTime), U" s]"));
	Graphics_setColour (graphics, Melder_RED);
	Graphics_text (graphics, 54.0, maximumValue, Melder_cat (U"参照：", reference.source.source.displayName.c_str(), U" [",
		Melder_single (reference.source.startTime), U"–", Melder_single (reference.source.endTime), U" s]"));
	Graphics_setColour (graphics, Melder_BLACK);
}

void exposeComparisonPlot (SegmentAcousticEditor me, GuiDrawingArea_ExposeEvent) {
	try {
		renderComparisonPlot (me);
	} catch (MelderError) {
		GuiLabel_setText (state (me) -> comparisonSummary, Melder_cat (U"曲线叠图失败：", Melder_getError()));
		Melder_clearError ();
	} catch (const std::exception &error) {
		GuiLabel_setText (state (me) -> comparisonSummary, Melder_cat (U"曲线叠图失败：", Melder_peek8to32_u (error.what())));
		Melder_clearError ();
	} catch (...) {
		GuiLabel_setText (state (me) -> comparisonSummary, U"曲线叠图失败：未知错误");
		Melder_clearError ();
	}
}

void renderFrequencyPlot (SegmentAcousticEditor me) {
	SegmentEditorState *editorState = state (me);
	Graphics graphics = editorState -> frequencyPlotGraphics.get();
	Graphics_clearWs (graphics);
	Graphics_setViewport (graphics, 42.0, GuiControl_getWidth (editorState -> frequencyPlotArea) - 12.0,
		12.0, GuiControl_getHeight (editorState -> frequencyPlotArea) - 28.0);
	if (editorState -> frequencyOverlays.empty()) {
		Graphics_setWindow (graphics, 0.0, 1.0, 0.0, 1.0);
		Graphics_text (graphics, 0.5, 0.5, U"当前分析没有可叠加的频率曲线");
		return;
	}
	double minimumValue = std::numeric_limits<double>::infinity();
	double maximumValue = - std::numeric_limits<double>::infinity();
	double minimumFrequency = std::numeric_limits<double>::infinity();
	double maximumFrequency = - std::numeric_limits<double>::infinity();
	for (const FrequencyOverlay &overlay : editorState -> frequencyOverlays) {
		for (const double value : overlay.targetValues) {
			minimumValue = std::min (minimumValue, value);
			maximumValue = std::max (maximumValue, value);
		}
		for (const double value : overlay.referenceValues) {
			minimumValue = std::min (minimumValue, value);
			maximumValue = std::max (maximumValue, value);
		}
		if (! overlay.frequencyHz.empty()) {
			minimumFrequency = std::min (minimumFrequency, overlay.frequencyHz.front());
			maximumFrequency = std::max (maximumFrequency, overlay.frequencyHz.back());
		}
	}
	if (! std::isfinite (minimumFrequency) || ! std::isfinite (minimumValue)) {
		Graphics_setWindow (graphics, 0.0, 1.0, 0.0, 1.0);
		Graphics_text (graphics, 0.5, 0.5, editorState -> frequencyOverlays.front().reason.c_str());
		return;
	}
	if (maximumFrequency <= minimumFrequency)
		maximumFrequency = minimumFrequency + 1.0;
	if (maximumValue <= minimumValue) {
		minimumValue -= 1.0;
		maximumValue += 1.0;
	} else {
		const double margin = (maximumValue - minimumValue) * 0.05;
		minimumValue -= margin;
		maximumValue += margin;
	}
	Graphics_setWindow (graphics, minimumFrequency, maximumFrequency, minimumValue, maximumValue);
	Graphics_drawInnerBox (graphics);
	for (const FrequencyOverlay &overlay : editorState -> frequencyOverlays) {
		for (size_t index = 1; index < overlay.targetValues.size(); index ++) {
			Graphics_setColour (graphics, Melder_BLUE);
			Graphics_line (graphics, overlay.frequencyHz [index - 1], overlay.targetValues [index - 1],
				overlay.frequencyHz [index], overlay.targetValues [index]);
		}
		for (size_t index = 1; index < overlay.referenceValues.size(); index ++) {
			Graphics_setColour (graphics, Melder_RED);
			Graphics_line (graphics, overlay.frequencyHz [index - 1], overlay.referenceValues [index - 1],
				overlay.frequencyHz [index], overlay.referenceValues [index]);
		}
	}
	if (! editorState -> frequencyOverlays.front().warning.empty()) {
		Graphics_setColour (graphics, Melder_RED);
		Graphics_text (graphics, minimumFrequency, maximumValue, editorState -> frequencyOverlays.front().warning.c_str());
	}
	Graphics_setColour (graphics, Melder_BLACK);
}

void exposeFrequencyPlot (SegmentAcousticEditor me, GuiDrawingArea_ExposeEvent) {
	try {
		renderFrequencyPlot (me);
	} catch (MelderError) {
		GuiLabel_setText (state (me) -> comparisonSummary, Melder_cat (U"频率叠图失败：", Melder_getError()));
		Melder_clearError ();
	} catch (const std::exception &error) {
		GuiLabel_setText (state (me) -> comparisonSummary, Melder_cat (U"频率叠图失败：", Melder_peek8to32_u (error.what())));
		Melder_clearError ();
	} catch (...) {
		GuiLabel_setText (state (me) -> comparisonSummary, U"频率叠图失败：未知错误");
		Melder_clearError ();
	}
}

void publishVotComparison (SegmentAcousticEditor me, AnalysisResult completedAnalyses [2], conststring32 title) {
	SegmentEditorState *editorState = state (me);
	ComparisonResult completedComparison = compareCompatibleMetrics (completedAnalyses [0], completedAnalyses [1]);
	std::vector<FrequencyOverlay> completedFrequencyOverlays = completedComparison.frequencyOverlays;
	editorState -> analyses [0] = completedAnalyses [0];
	editorState -> analyses [1] = completedAnalyses [1];
	editorState -> comparison = std::move (completedComparison);
	editorState -> frequencyOverlays = std::move (completedFrequencyOverlays);
	autoMelderString summary;
	MelderString_append (& summary, title, U"\n",
		U"目标：", editorState -> comparison -> target.source.displayName.c_str(), U" [",
		Melder_single (editorState -> comparison -> target.startTime), U"–", Melder_single (editorState -> comparison -> target.endTime), U" s]；",
		Melder_single (editorState -> comparison -> target.endTime - editorState -> comparison -> target.startTime), U" s\n",
		U"参照：", editorState -> comparison -> reference.source.displayName.c_str(), U" [",
		Melder_single (editorState -> comparison -> reference.startTime), U"–", Melder_single (editorState -> comparison -> reference.endTime), U" s]；",
		Melder_single (editorState -> comparison -> reference.endTime - editorState -> comparison -> reference.startTime), U" s\n");
	if (! editorState -> comparison -> rows.empty() && ! editorState -> comparison -> rows.front().warning.empty())
		MelderString_append (& summary, U"采样率提示：", editorState -> comparison -> rows.front().warning.c_str(), U"\n");
	MelderString_append (& summary, U"指标/单位\t目标值/状态/原因\t参照值/状态/原因\t目标−参照\t可比性/提示\n");
	for (const MetricComparison &row : editorState -> comparison -> rows) {
		MelderString_append (& summary, row.metricId.c_str(), U" [", row.unit.c_str(), U"]\t");
		if (row.targetValue && row.targetStatus != MetricStatus::unavailable)
			MelderString_append (& summary, Melder_double (row.targetValue.value()));
		else
			MelderString_append (& summary, U"NA");
		MelderString_append (& summary, U" / ", editorMetricStatusName (row.targetStatus), U" / ", row.targetReason.c_str(), U"\t");
		if (row.referenceValue && row.referenceStatus != MetricStatus::unavailable)
			MelderString_append (& summary, Melder_double (row.referenceValue.value()));
		else
			MelderString_append (& summary, U"NA");
		MelderString_append (& summary, U" / ", editorMetricStatusName (row.referenceStatus), U" / ", row.referenceReason.c_str(), U"\t");
		if (row.difference)
			MelderString_append (& summary, Melder_double (row.difference.value()));
		else
			MelderString_append (& summary, U"不可比较");
		MelderString_append (& summary, U"\t", row.reason.empty() ? U"可比较" : row.reason.c_str());
		if (! row.warning.empty())
			MelderString_append (& summary, U"；", row.warning.c_str());
		if (! row.reason.empty())
			MelderString_append (& summary, U"；目标原因：", row.targetReason.c_str(), U"；参照原因：", row.referenceReason.c_str());
		MelderString_appendCharacter (& summary, U'\n');
	}
	GuiLabel_setText (editorState -> comparisonSummary, summary.string);
	for (integer side = 0; side < 2; side ++)
		Graphics_updateWs (editorState -> waveformGraphics [side].get());
	Graphics_updateWs (editorState -> comparisonPlotGraphics.get());
	Graphics_updateWs (editorState -> frequencyPlotGraphics.get());
}

AnalysisResult estimateVotSide (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	const SegmentAnalysisSelection &selected = selectionFor (me, side);
	Melder_require (selected.analysisKind == AnalysisKind::VOT,
		U"当前只有 VOT 分析核心可运行；其他分析类别尚未实现。");
	const std::shared_ptr<SegmentSourceData> source = editorState -> activeSource [side];
	Melder_require (source, side == 0 ? U"请先设置有效的目标来源和范围。" : U"请先设置有效的参照来源和范围。");
	Melder_require (selected.metadata.startTime < selected.metadata.endTime &&
		selected.metadata.startTime >= source -> xmin && selected.metadata.endTime <= source -> xmax,
		U"请先在目标和参照两侧分别输入并应用有效时间范围。");
	autoSound samples = extractPreview (*source, selected.metadata.startTime, selected.metadata.endTime);
	SegmentInput input;
	input.samples = samples.get();
	input.metadata = selected.metadata;
	input.metadata.source = source -> identity;
	return analyseVOT (input, {}, {}, VOTBoundaryMode::estimateCandidates);
}

void estimateAndCompare (SegmentAcousticEditor me) {
	Melder_require (my selection.reference, U"请先设置并应用有效的参照来源和范围。");
	AnalysisResult completedAnalyses [2];
	for (integer side = 0; side < 2; side ++) {
		completedAnalyses [side] = estimateVotSide (me, side);
		state (me) -> candidateAnalyses [side] = completedAnalyses [side];
		const MetricResult *burst = findResultMetric (completedAnalyses [side], U"burst_time_candidate");
		const MetricResult *voicing = findResultMetric (completedAnalyses [side], U"voicing_time_candidate");
		GuiText_setString (state (me) -> boundaryBurstField [side], burst && burst -> value ? Melder_single (burst -> value.value()) : U"");
		GuiText_setString (state (me) -> boundaryVoicingField [side], voicing && voicing -> value ? Melder_single (voicing -> value.value()) : U"");
	}
	publishVotComparison (me, completedAnalyses, U"VOT 自动候选对照；可编辑两侧边界后点“确认边界并比较”。");
}

void confirmAndCompareBoundaries (SegmentAcousticEditor me) {
	Melder_require (my selection.reference, U"请先设置并应用有效的参照来源和范围。");
	AnalysisResult completedAnalyses [2];
	for (integer side = 0; side < 2; side ++) {
		SegmentEditorState *editorState = state (me);
		const SegmentAnalysisSelection &selected = selectionFor (me, side);
		const std::shared_ptr<SegmentSourceData> source = editorState -> activeSource [side];
		Melder_require (selected.analysisKind == AnalysisKind::VOT && source,
			U"请为目标和参照两侧选择有效来源并选择 VOT 分析。");
		Melder_require (selected.metadata.startTime < selected.metadata.endTime &&
			selected.metadata.startTime >= source -> xmin && selected.metadata.endTime <= source -> xmax,
			U"请先在目标和参照两侧分别应用有效时间范围。");
		double burst = 0.0, voicing = 0.0;
		Melder_require (readVotBoundaries (me, side, & burst, & voicing),
			U"请输入有限的 burst 和 voicing 边界；0 和负时间都是有效输入。");
		autoSound samples = extractPreview (*source, selected.metadata.startTime, selected.metadata.endTime);
		SegmentInput input;
		input.samples = samples.get();
		input.metadata = selected.metadata;
		input.metadata.source = source -> identity;
		const AnalysisResult *candidates = editorState -> candidateAnalyses [side] ?
			& editorState -> candidateAnalyses [side].value() : nullptr;
		completedAnalyses [side] = confirmVOTBoundaries (input, candidates, burst, voicing);
	}
	publishVotComparison (me, completedAnalyses, U"VOT 人工确认结果；候选估计、最终边界、两侧状态和原因均予保留。");
}

void exportComparison (SegmentAcousticEditor me) {
	SegmentEditorState *editorState = state (me);
	Melder_require (editorState -> comparison, U"请先运行目标/参照比较，再导出结果。");
	autostring32 path = GuiFileSelect_getOutfileName (my windowForm, U"导出目标/参照比较 TSV", U"segment-comparison.tsv");
	if (! path)
		return;
	autoMelderString serialized;
	ComparisonResult_toTsv (editorState -> comparison.value(), & serialized);
	writeSegmentAnalysisTsvAtomically (path.get(), serialized.string);
	GuiLabel_setText (editorState -> sourceStatus [0], Melder_cat (U"目标/参照比较 TSV 已保存：", path.get()));
}

void estimateAndCompareButton (SegmentAcousticEditor me, GuiButtonEvent) {
	safelyDo (me, 0, U"目标/参照候选分析失败", [&] { estimateAndCompare (me); });
}

void confirmAndCompareButton (SegmentAcousticEditor me, GuiButtonEvent) {
	safelyDo (me, 0, U"目标/参照边界确认失败", [&] { confirmAndCompareBoundaries (me); });
}

void exportComparisonButton (SegmentAcousticEditor me, GuiButtonEvent) {
	safelyDo (me, 0, U"导出比较结果失败", [&] { exportComparison (me); });
}

void chooseAndApply (SegmentAcousticEditor me, integer side) {
	safelyDo (me, side, U"更换来源失败", [&] { installObjectChoice (me, side); });
}

void refreshSources (SegmentAcousticEditor me, integer side) {
	safelyDo (me, side, U"刷新来源失败", [&] {
		refreshObjectChoices (me);
		setStatus (me, side, U"对象列表已刷新；应用来源后才会替换此侧来源。");
	});
}

void chooseFiles (SegmentAcousticEditor me, integer side) {
	safelyDo (me, side, U"加载音频失败", [&] { loadFiles (me, side); });
}

void applyTargetRange (SegmentAcousticEditor me, GuiButtonEvent) { safelyDo (me, 0, U"目标范围无效", [&] { applyRange (me, 0); }); }
void applyReferenceRange (SegmentAcousticEditor me, GuiButtonEvent) { safelyDo (me, 1, U"参照范围无效", [&] { applyRange (me, 1); }); }
void applyTargetSource (SegmentAcousticEditor me, GuiButtonEvent) { chooseAndApply (me, 0); }
void applyReferenceSource (SegmentAcousticEditor me, GuiButtonEvent) { chooseAndApply (me, 1); }
void refreshTargetButton (SegmentAcousticEditor me, GuiButtonEvent) { refreshSources (me, 0); }
void refreshReferenceButton (SegmentAcousticEditor me, GuiButtonEvent) { refreshSources (me, 1); }
void targetFiles (SegmentAcousticEditor me, GuiButtonEvent) { chooseFiles (me, 0); }
void referenceFiles (SegmentAcousticEditor me, GuiButtonEvent) { chooseFiles (me, 1); }

void playSide (SegmentAcousticEditor me, integer side) {
	SegmentEditorState *editorState = state (me);
	const auto source = editorState -> activeSource [side];
	Melder_require (source, U"请先加载此侧的来源。");
	Melder_require (selectionFor (me, side).metadata.startTime < selectionFor (me, side).metadata.endTime,
		U"请先输入并应用此侧的有效片段范围。");
	const double start = selectionFor (me, side).playbackStartTime;
	const double end = selectionFor (me, side).playbackEndTime;
	if (source -> sound)
		Sound_playPart (source -> sound.get(), start, end, nullptr, nullptr);
	else
		LongSound_playPart (source -> longSound.get(), start, end, nullptr, nullptr);
}

void playTarget (SegmentAcousticEditor me, GuiButtonEvent) { safelyDo (me, 0, U"试听目标失败", [&] { playSide (me, 0); }); }
void playReference (SegmentAcousticEditor me, GuiButtonEvent) { safelyDo (me, 1, U"试听参照失败", [&] { playSide (me, 1); }); }

void playSequential (SegmentAcousticEditor me, GuiButtonEvent) {
	safelyDo (me, 0, U"依次试听失败", [&] {
		Melder_require (my selection.reference, U"请先为参照侧选择来源并应用有效范围。");
		const SegmentAnalysisSelection &targetSelection = my selection.target;
		const SegmentAnalysisSelection &referenceSelection = my selection.reference.value();
		Melder_require (targetSelection.metadata.startTime < targetSelection.metadata.endTime &&
			referenceSelection.metadata.startTime < referenceSelection.metadata.endTime,
			U"请先分别应用目标和参照的片段范围。");
		const auto targetSource = state (me) -> activeSource [0];
		const auto referenceSource = state (me) -> activeSource [1];
		Melder_require (targetSource && referenceSource, U"目标或参照来源尚未加载。");
		autoSound targetPart = extractPreview (*targetSource, targetSelection.playbackStartTime, targetSelection.playbackEndTime);
		autoSound referencePart = extractPreview (*referenceSource, referenceSelection.playbackStartTime, referenceSelection.playbackEndTime);
		autoSound targetMono = targetPart -> ny == 1 ? targetPart.move() : Sound_convertToMono (targetPart.get());
		autoSound referenceMono = referencePart -> ny == 1 ? referencePart.move() : Sound_convertToMono (referencePart.get());
		if (std::abs (targetMono -> dx - referenceMono -> dx) > 1.0e-12)
			referenceMono = Sound_resample (referenceMono.get(), 1.0 / targetMono -> dx, 50);
		autoSoundList pieces = SoundList_create();
		pieces -> addItem_move (targetMono.move());
		pieces -> addItem_move (referenceMono.move());
		autoSound sequential = Sounds_concatenate (pieces.get(), 0.0);
		Sound_play (sequential.get(), nullptr, nullptr);
	});
}

} // namespace

void structSegmentAcousticEditor :: v9_destroy () noexcept {
	delete static_cast<SegmentEditorState *> (our d_privateState);
	our d_privateState = nullptr;
	SegmentAcousticEditor_Parent :: v9_destroy ();
}

void structSegmentAcousticEditor :: v1_info () {
	SegmentAcousticEditor_Parent :: v1_info ();
	MelderInfo_writeLine (U"Target source: ", our selection.target.metadata.source.displayName.c_str());
	MelderInfo_writeLine (U"Target interval: ", our selection.target.metadata.startTime, U"–", our selection.target.metadata.endTime);
	if (our selection.reference) {
		MelderInfo_writeLine (U"Reference source: ", our selection.reference -> metadata.source.displayName.c_str());
		MelderInfo_writeLine (U"Reference interval: ", our selection.reference -> metadata.startTime, U"–", our selection.reference -> metadata.endTime);
	} else {
		MelderInfo_writeLine (U"Reference source: not selected");
	}
	if (state (this) -> comparison) {
		MelderInfo_writeLine (U"Comparison rows:");
		for (const MetricComparison &row : state (this) -> comparison -> rows) {
			MelderInfo_writeLine (row.metricId.c_str(), U" target=", row.targetValue ? Melder_double (row.targetValue.value()) : U"NA",
				U" reference=", row.referenceValue ? Melder_double (row.referenceValue.value()) : U"NA",
				U" difference=", row.difference ? Melder_double (row.difference.value()) : U"NA",
				U" status=", row.reason.empty() ? U"comparable" : U"not comparable",
				row.reason.empty() ? U"" : Melder_cat (U" reason=", row.reason.c_str()),
				row.warning.empty() ? U"" : Melder_cat (U" warning=", row.warning.c_str()));
		}
	} else {
		MelderInfo_writeLine (U"Comparison result: not calculated");
	}
}

void structSegmentAcousticEditor :: v_createChildren () {
	SegmentEditorState *editorState = state (this);
	GuiLabel_createShown (our windowForm, 18, 555, 12, 34, U"目标片段", GuiLabel_BOLD);
	GuiLabel_createShown (our windowForm, 590, -18, 12, 34, U"参照片段", GuiLabel_BOLD);
	for (integer side = 0; side < 2; side ++) {
		const int left = side == 0 ? 18 : 590;
		const int right = side == 0 ? 555 : -18;
		GuiLabel_createShown (our windowForm, left, left + 70, 40, 64, U"来源", GuiLabel_RIGHT);
		editorState -> sourceMenu [side] = GuiOptionMenu_createShown (our windowForm, left + 76, left + 300, 39, 65, 0);
		GuiButton_createShown (our windowForm, left + 306, left + 385, 39, 65, U"应用来源", side == 0 ? applyTargetSource : applyReferenceSource, this, 0);
		GuiButton_createShown (our windowForm, left + 391, left + 445, 39, 65, U"刷新",
			side == 0 ? refreshTargetButton : refreshReferenceButton, this, 0);
		const int panelRight = side == 0 ? 555 : 1142;
		GuiButton_createShown (our windowForm, left + 451, panelRight, 39, 65, U"从文件夹读取…",
			side == 0 ? targetFiles : referenceFiles, this, GuiButton_MULTILINE);
		GuiLabel_createShown (our windowForm, left, left + 70, 69, 93, U"分析", GuiLabel_RIGHT);
		editorState -> analysisMenu [side] = GuiOptionMenu_createShown (our windowForm, left + 76, left + 260, 68, 94, 0);
		GuiOptionMenu_addOption (editorState -> analysisMenu [side], U"元音鼻化");
		GuiOptionMenu_addOption (editorState -> analysisMenu [side], U"鼻音辅音");
		GuiOptionMenu_addOption (editorState -> analysisMenu [side], U"R 音");
		GuiOptionMenu_addOption (editorState -> analysisMenu [side], U"VOT");
		GuiOptionMenu_setValue (editorState -> analysisMenu [side], 4);
		GuiLabel_createShown (our windowForm, left + 270, left + 315, 69, 93, U"开始", GuiLabel_RIGHT);
		editorState -> startField [side] = GuiText_createShown (our windowForm, left + 320, left + 385, 68, 94, 0);
		GuiLabel_createShown (our windowForm, left + 390, left + 435, 69, 93, U"结束", GuiLabel_RIGHT);
		editorState -> endField [side] = GuiText_createShown (our windowForm, left + 440, left + 505, 68, 94, 0);
		GuiButton_createShown (our windowForm, left + 76, left + 165, 98, 125, U"应用范围", side == 0 ? applyTargetRange : applyReferenceRange, this, 0);
		GuiButton_createShown (our windowForm, left + 174, left + 260, 98, 125, U"试听本侧", side == 0 ? playTarget : playReference, this, 0);
		GuiLabel_createShown (our windowForm, left, left + 70, 129, 153, U"释放边界", GuiLabel_RIGHT);
		editorState -> boundaryBurstField [side] = GuiText_createShown (our windowForm, left + 76, left + 156, 129, 153, 0);
		GuiLabel_createShown (our windowForm, left + 160, left + 230, 129, 153, U"浊音边界", GuiLabel_RIGHT);
		editorState -> boundaryVoicingField [side] = GuiText_createShown (our windowForm, left + 236, left + 316, 129, 153, 0);
		GuiLabel_createShown (our windowForm, left, right, 155, 177, U"波形预览（红/蓝为候选，绿为确认边界）", GuiLabel_BOLD);
		editorState -> waveformArea [side] = GuiDrawingArea_createShown (our windowForm,
			left, right, 178, 323, exposeWaveform, nullptr, nullptr, nullptr, nullptr, this, 0);
		GuiLabel_createShown (our windowForm, left, right, 325, 349, U"频谱预览", GuiLabel_BOLD);
		editorState -> spectrogramArea [side] = GuiDrawingArea_createShown (our windowForm,
			left, right, 350, 493, exposeSpectrogram, nullptr, nullptr, nullptr, nullptr, this, 0);
		editorState -> sourceStatus [side] = GuiLabel_createShown (our windowForm, left, right, 496, 525,
			side == 0 ? U"尚未设置目标来源和片段范围。" : U"尚未设置参照来源和片段范围；目标侧状态保持不变。", GuiLabel_MULTILINE);
		editorState -> previewStatus [side] = GuiLabel_createShown (our windowForm, left, right, 527, 552, U"", 0);
		(void) left;
	}
	GuiButton_createShown (our windowForm, 210, 410, 570, 598, U"依次试听目标与参照", playSequential, this, GuiButton_ATTRACTIVE);
	GuiButton_createShown (our windowForm, 420, 670, 570, 598, U"自动估计候选", estimateAndCompareButton, this, 0);
	GuiButton_createShown (our windowForm, 680, 930, 570, 598, U"确认边界并比较", confirmAndCompareButton, this, GuiButton_ATTRACTIVE);
	GuiButton_createShown (our windowForm, 940, -20, 570, 598, U"导出 TSV…", exportComparisonButton, this, 0);
	GuiLabel_createShown (our windowForm, 20, -20, 603, 624,
		U"目标与参照来源和范围独立；先估计候选，再编辑两侧释放/浊音边界并确认。零和负时间有效。", GuiLabel_CENTRE);
	editorState -> comparisonSummary = GuiLabel_createShown (our windowForm, 20, -20, 626, 790,
		U"尚无比较结果。设置目标和参照的来源与范围后，自动估计候选，或直接输入两侧边界并确认。", GuiLabel_MULTILINE);
	GuiLabel_createShown (our windowForm, 20, 575, 792, 813, U"时间曲线叠图（0–100%）", GuiLabel_BOLD);
	GuiLabel_createShown (our windowForm, 590, -20, 792, 813, U"共同频率网格叠图（Hz）", GuiLabel_BOLD);
	editorState -> comparisonPlotArea = GuiDrawingArea_createShown (our windowForm,
		20, 575, 814, 927, exposeComparisonPlot, nullptr, nullptr, nullptr, nullptr, this, 0);
	editorState -> frequencyPlotArea = GuiDrawingArea_createShown (our windowForm,
		590, -20, 814, 927, exposeFrequencyPlot, nullptr, nullptr, nullptr, nullptr, this, 0);
	GuiLabel_createShown (our windowForm, 20, -20, 929, 953,
		U"未实现的鼻化、鼻辅音与 R 音算法会明确提示，不会套用 VOT 结果。", GuiLabel_CENTRE);

	GuiOptionMenu_addOption (editorState -> sourceMenu [0], editorState -> initialName.c_str());
	editorState -> choices [0].push_back ({ editorState -> initialObjectId, editorState -> activeSource [0], editorState -> initialName });
	GuiOptionMenu_setValue (editorState -> sourceMenu [0], 1);
	if (editorState -> activeSource [0])
		syncSourceIdentity (this, 0, false);
	GuiOptionMenu_addOption (editorState -> sourceMenu [1], U"（未选择）");
	editorState -> choices [1].push_back ({ {}, {}, U"（未选择）" });
	GuiOptionMenu_setValue (editorState -> sourceMenu [1], 1);
	refreshObjectChoices (this);
	for (integer side = 0; side < 2; side ++) {
		const SegmentAnalysisSelection *sideSelection = side == 0 ? & our selection.target : our selection.reference ? & our selection.reference.value() : nullptr;
		if (sideSelection)
			GuiOptionMenu_setValue (editorState -> analysisMenu [side], (int) sideSelection -> analysisKind + 1);
		if (sideSelection && std::isfinite (sideSelection -> metadata.startTime) && std::isfinite (sideSelection -> metadata.endTime) &&
			sideSelection -> metadata.startTime < sideSelection -> metadata.endTime) {
			GuiText_setString (editorState -> startField [side], Melder_single (sideSelection -> metadata.startTime));
			GuiText_setString (editorState -> endField [side], Melder_single (sideSelection -> metadata.endTime));
		}
	}
}

void structSegmentAcousticEditor :: v_createMenus () {
	SegmentAcousticEditor_Parent :: v_createMenus ();
}

autoSegmentAcousticEditor SegmentAcousticEditor_create (Sound initialTargetSound, LongSound initialTargetLongSound,
		std::optional<integer> initialObjectId, conststring32 initialSourceName,
		double initialStartTime, double initialEndTime) {
	autoSegmentAcousticEditor me = Thing_new (SegmentAcousticEditor);
	auto editorState = std::make_unique<SegmentEditorState>();
	SegmentAnalysisSelection target {};
	target.metadata.source.objectId = initialObjectId;
	target.metadata.source.displayName = initialSourceName ? initialSourceName : U"target";
	target.metadata.startTime = initialStartTime;
	target.metadata.endTime = initialEndTime;
	target.playbackStartTime = initialStartTime;
	target.playbackEndTime = initialEndTime;
	editorState -> initialTarget = target;
	editorState -> initialObjectId = initialObjectId;
	editorState -> initialName = initialSourceName ? initialSourceName : U"target";
	if (initialTargetSound)
		editorState -> activeSource [0] = copyPraatSource (initialTargetSound, initialObjectId, editorState -> initialName.c_str());
	else if (initialTargetLongSound)
		editorState -> activeSource [0] = copyPraatSource (initialTargetLongSound, initialObjectId, editorState -> initialName.c_str());
	my selection.target = target;
	my d_privateState = editorState.release();
	Editor_init (me.get(), 0, 0, 1160, 970, U"辅音片段目标/参照对比", nullptr);
	SegmentEditorState *liveState = state (me.get());
	for (integer side = 0; side < 2; side ++) {
		liveState -> waveformGraphics [side] = Graphics_create_xmdrawingarea (liveState -> waveformArea [side]);
		liveState -> spectrogramGraphics [side] = Graphics_create_xmdrawingarea (liveState -> spectrogramArea [side]);
		Graphics_setWsViewport (liveState -> waveformGraphics [side].get(), 0.0, GuiControl_getWidth (liveState -> waveformArea [side]),
			0.0, GuiControl_getHeight (liveState -> waveformArea [side]));
		Graphics_setWsWindow (liveState -> waveformGraphics [side].get(), 0.0, GuiControl_getWidth (liveState -> waveformArea [side]),
			0.0, GuiControl_getHeight (liveState -> waveformArea [side]));
		Graphics_setWsViewport (liveState -> spectrogramGraphics [side].get(), 0.0, GuiControl_getWidth (liveState -> spectrogramArea [side]),
			0.0, GuiControl_getHeight (liveState -> spectrogramArea [side]));
		Graphics_setWsWindow (liveState -> spectrogramGraphics [side].get(), 0.0, GuiControl_getWidth (liveState -> spectrogramArea [side]),
			0.0, GuiControl_getHeight (liveState -> spectrogramArea [side]));
		Graphics_updateWs (liveState -> waveformGraphics [side].get());
		Graphics_updateWs (liveState -> spectrogramGraphics [side].get());
	}
	liveState -> comparisonPlotGraphics = Graphics_create_xmdrawingarea (liveState -> comparisonPlotArea);
	Graphics_setWsViewport (liveState -> comparisonPlotGraphics.get(), 0.0, GuiControl_getWidth (liveState -> comparisonPlotArea),
		0.0, GuiControl_getHeight (liveState -> comparisonPlotArea));
	Graphics_setWsWindow (liveState -> comparisonPlotGraphics.get(), 0.0, GuiControl_getWidth (liveState -> comparisonPlotArea),
		0.0, GuiControl_getHeight (liveState -> comparisonPlotArea));
	Graphics_updateWs (liveState -> comparisonPlotGraphics.get());
	liveState -> frequencyPlotGraphics = Graphics_create_xmdrawingarea (liveState -> frequencyPlotArea);
	Graphics_setWsViewport (liveState -> frequencyPlotGraphics.get(), 0.0, GuiControl_getWidth (liveState -> frequencyPlotArea),
		0.0, GuiControl_getHeight (liveState -> frequencyPlotArea));
	Graphics_setWsWindow (liveState -> frequencyPlotGraphics.get(), 0.0, GuiControl_getWidth (liveState -> frequencyPlotArea),
		0.0, GuiControl_getHeight (liveState -> frequencyPlotArea));
	Graphics_updateWs (liveState -> frequencyPlotGraphics.get());
	return me;
}
