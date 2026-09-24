#ifndef _SegmentAcousticVOT_h_
#define _SegmentAcousticVOT_h_

#include "LongSound.h"
#include "SegmentAcousticAnalysis.h"

#include <optional>

void praat_Sound_writeVOTAnalysisToFile (Sound sound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings, conststring32 resultFileName,
		SourceKind sourceKind = SourceKind::sound, conststring32 sourceName = nullptr,
		std::optional<integer> objectId = {}, std::optional<std::u32string> filePath = {});
void praat_LongSound_writeVOTAnalysisToFile (LongSound longSound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings, conststring32 resultFileName,
		std::optional<integer> objectId = {});

#endif
