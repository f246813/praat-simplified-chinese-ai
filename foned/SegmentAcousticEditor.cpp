#include "SegmentAcousticEditor.h"

#include "Sound_and_Spectrogram.h"
#include "Spectrogram.h"
#include "EditorM.h"
#include "praat.h"
#include "melder_files.h"

#include <cmath>
#include <exception>
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
	GuiLabel sourceStatus [2] { nullptr, nullptr };
	GuiLabel previewStatus [2] { nullptr, nullptr };
	GuiDrawingArea waveformArea [2] { nullptr, nullptr };
	GuiDrawingArea spectrogramArea [2] { nullptr, nullptr };
	autoGraphics waveformGraphics [2];
	autoGraphics spectrogramGraphics [2];
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
		GuiLabel_createShown (our windowForm, left, right, 129, 153, U"波形预览", GuiLabel_BOLD);
		editorState -> waveformArea [side] = GuiDrawingArea_createShown (our windowForm,
			left, right, 154, 332, exposeWaveform, nullptr, nullptr, nullptr, nullptr, this, 0);
		GuiLabel_createShown (our windowForm, left, right, 334, 358, U"频谱预览", GuiLabel_BOLD);
		editorState -> spectrogramArea [side] = GuiDrawingArea_createShown (our windowForm,
			left, right, 359, 506, exposeSpectrogram, nullptr, nullptr, nullptr, nullptr, this, 0);
		editorState -> sourceStatus [side] = GuiLabel_createShown (our windowForm, left, right, 510, 540,
			side == 0 ? U"尚未设置目标来源和片段范围。" : U"尚未设置参照来源和片段范围；目标侧状态保持不变。", GuiLabel_MULTILINE);
		editorState -> previewStatus [side] = GuiLabel_createShown (our windowForm, left, right, 542, 565, U"", 0);
		(void) left;
	}
	GuiButton_createShown (our windowForm, 450, 710, 570, 598, U"依次试听目标与参照", playSequential, this, GuiButton_ATTRACTIVE);
	GuiLabel_createShown (our windowForm, 20, -20, 601, 630,
		U"目标与参照的来源、分析类型、时间范围和试听区间独立保存；分析类型随“应用范围”一并保存。", GuiLabel_CENTRE);

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
	Editor_init (me.get(), 0, 0, 1160, 640, U"辅音片段目标/参照对比", nullptr);
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
	return me;
}
