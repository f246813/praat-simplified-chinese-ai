#ifndef _SoundEditor_h_
#define _SoundEditor_h_
/* SoundEditor.h
 *
 * Copyright (C) 1992-2005,2007,2009-2012,2014-2016,2018,2020,2022 Paul Boersma
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

#include "FunctionEditor.h"
#include "LongSoundArea.h"
#include "SoundAnalysisArea.h"

#include <optional>
#include <string>

Thing_define (SoundEditor, FunctionEditor) {
	DEFINE_FunctionArea (1, SoundArea, soundArea)
	DEFINE_FunctionArea (2, SoundAnalysisArea, soundAnalysisArea)
	bool votStateHasSelection { false };
	double votStateSelectionStart { 0.0 };
	double votStateSelectionEnd { 0.0 };
	std::optional<double> votAnalysisStartTime;
	std::optional<double> votAnalysisEndTime;
	std::optional<double> votFixedContextStartTime;
	std::optional<double> votFixedContextEndTime;
	std::optional<double> votBurstTime;
	std::optional<double> votVoicingTime;
	std::optional<double> votValueMs;
	std::u32string votFailureReason;
	std::u32string votProgressText;
	std::u32string votResultStatus;
	std::string votCurrentJobId;
	integer votRequestGeneration { 0 };
	integer votMode { 1 };
	integer votTargetPhoneIndex { 0 };
	std::u32string votLanguage;
	std::u32string votTranscript;
	std::u32string votPhonemes;
	UiForm votForm { nullptr };
	double votBurstThresholdDb { 6.0 };
	double votPitchFloorHz { 75.0 };
	bool votCalculationAttempted { false };
	bool votValueIsCandidate { false };
	bool votManualConfirmed { false };
	bool votNeedsRecalculation { true };
	bool votUpdatingForm { false };

	void v1_dataChanged (Editor sender) override;
	void v_createMenuItems_help (EditorMenu menu)
		override;
	void v_updateText () override;
	void v_createMenus () override;
	void v_createMenusAfterFunctionAreas () override;
	bool v_hasAiToolbar () override { return true; }
	void v_distributeAreas () override {
		if (our soundAnalysisArea() -> hasContentToShow ()) {
			our soundArea() -> setGlobalYRange_fraction (0.5, 1.0);
			our soundAnalysisArea() -> setGlobalYRange_fraction (0.0, 0.5);
		} else {
			our soundArea() -> setGlobalYRange_fraction (0.0, 1.0);
			our soundAnalysisArea() -> setGlobalYRange_fraction (0.0, 0.0);
		}
	}
	void v_draw () override {
		FunctionArea_prepareCanvas (our soundArea().get());
		if (our soundAnalysisArea() -> instancePref_pulses_show())
			our soundAnalysisArea() -> v_draw_analysis_pulses ();
		FunctionArea_drawInside (our soundArea().get());
		if (our soundAnalysisArea() -> hasContentToShow ()) {
			FunctionArea_prepareCanvas (our soundAnalysisArea().get());
			our soundAnalysisArea() -> v_draw_analysis ();
		}
	}
	void v_play (double startTime, double endTime) override {
		SoundArea_play (our soundArea().get(), startTime, endTime);
	}
	void v_drawLegends () override {
		const bool pulsesAreVisible = our soundAnalysisArea() -> hasPulsesToShow ();
		FunctionArea_drawLegend (our soundArea().get(),
			pulsesAreVisible ? FunctionArea_legend_POLES U" %%derived pulses" : nullptr,
			Melder_GREY,
			FunctionArea_legend_WAVEFORM U" ##modifiable sound",
			DataGui_defaultForegroundColour (our soundArea().get(), false)
		);
		SoundAnalysisArea_drawDefaultLegends (our soundAnalysisArea().get());
	}
};

autoSoundEditor SoundEditor_create (
	conststring32 title,
	SampledXY data   // either a Sound or a LongSound
);

/* End of file SoundEditor.h */
#endif
