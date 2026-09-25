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

#include <exception>

Thing_implement (SoundEditor, FunctionEditor, 0);

static void menu_cb_SoundEditorHelp (SoundEditor, EDITOR_ARGS) { Melder_help (U"SoundEditor"); }
static void menu_cb_LongSoundEditorHelp (SoundEditor, EDITOR_ARGS) { Melder_help (U"LongSoundEditor"); }

static std::optional<double> editorOptionalVotBoundary (double value) {
	return isundef (value) ? std::optional<double> {} : std::optional<double> { value };
}

static void menu_cb_SoundEditor_VOT (SoundEditor me, EDITOR_ARGS) {
	EDITOR_FORM (U"VOT analysis", U"VOT...")
		REAL_OR_UNDEFINED (startTime, U"Start time (s)", U"undefined")
		REAL_OR_UNDEFINED (endTime, U"End time (s)", U"undefined")
		REAL_OR_UNDEFINED (burstTime, U"Burst/release time (s); undefined for a candidate", U"undefined")
		REAL_OR_UNDEFINED (voicingTime, U"Voicing onset time (s); undefined for a candidate", U"undefined")
		REAL (burstThresholdDb, U"Minimum burst rise (dB)", U"6.0")
		REAL (pitchFloorHz, U"Pitch floor (Hz)", U"75.0")
	EDITOR_OK
		const SampledXY data = static_cast <SampledXY> (my data());
		const bool hasSelection = my startSelection < my endSelection;
		SET_REAL (startTime, hasSelection ? my startSelection : data -> xmin)
		SET_REAL (endTime, hasSelection ? my endSelection : data -> xmax)
		SET_REAL (burstTime, undefined)
		SET_REAL (voicingTime, undefined)
		SET_REAL (burstThresholdDb, 6.0)
		SET_REAL (pitchFloorHz, 75.0)
	EDITOR_DO
		try {
			VOTCandidateSettings settings;
			settings.burstThresholdDb = burstThresholdDb;
			settings.pitchFloorHz = pitchFloorHz;
			const std::optional<double> actualBurstTime = editorOptionalVotBoundary (burstTime);
			const std::optional<double> actualVoicingTime = editorOptionalVotBoundary (voicingTime);
			AnalysisResult result = [&] () {
				if (Thing_isa (my data(), classLongSound))
					return praat_LongSound_analyseVOT (static_cast <LongSound> (my data()), startTime, endTime,
						actualBurstTime, actualVoicingTime, settings);
				const Sound sound = static_cast <Sound> (my data());
				return praat_Sound_analyseVOT (sound, startTime, endTime, actualBurstTime,
					actualVoicingTime, settings, SourceKind::sound, sound -> name.get());
			} ();
			autoMelderString summary;
			AnalysisResult_toInfoSummary (result, & summary);
			Melder_information (summary.string);
		} catch (const std::exception &error) {
			Melder_throw (U"VOT analysis failed: ", Melder_peek8to32_u (error.what()));
		}
	EDITOR_END
}

static void gui_button_cb_vot (SoundEditor me, GuiButtonEvent /* event */) {
	Editor_doMenuCommand (me, U"VOT...", 0, nullptr, nullptr, nullptr);
}

void structSoundEditor :: v_createMenus () {
	SoundEditor_Parent :: v_createMenus ();
	Editor_addCommand (this, U"Query", U"VOT...", GuiMenu_HIDDEN, menu_cb_SoundEditor_VOT);
}

void structSoundEditor :: v_createExtraToolbarButtons (int &x, int buttonWidth, int buttonSpacing) {
	GuiButton_createShown (our windowForm, x, x + buttonWidth, -4 - Gui_PUSHBUTTON_HEIGHT, -4,
		U"VOT", gui_button_cb_vot, this, 0);
	x += buttonWidth + buttonSpacing;
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
