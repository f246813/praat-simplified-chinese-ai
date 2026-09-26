#ifndef _SegmentAcousticVOT_h_
#define _SegmentAcousticVOT_h_

#include "LongSound.h"
#include "SegmentAcousticAnalysis.h"

#include <optional>

AnalysisResult praat_Sound_analyseVOT (Sound sound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings,
		SourceKind sourceKind = SourceKind::sound, conststring32 sourceName = nullptr,
		std::optional<integer> objectId = {}, std::optional<std::u32string> filePath = {});
AnalysisResult praat_LongSound_analyseVOT (LongSound longSound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings, std::optional<integer> objectId = {});

void praat_Sound_writeVOTAnalysisToFile (Sound sound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings, conststring32 resultFileName,
		SourceKind sourceKind = SourceKind::sound, conststring32 sourceName = nullptr,
		std::optional<integer> objectId = {}, std::optional<std::u32string> filePath = {});
void praat_LongSound_writeVOTAnalysisToFile (LongSound longSound, double startTime, double endTime,
		std::optional<double> burstTime, std::optional<double> voicingTime,
		const VOTCandidateSettings &settings, conststring32 resultFileName,
		std::optional<integer> objectId = {});

void praat_Sound_writeVOTAudioSnapshot (Sound sound, integer objectId,
		integer snapshotStartSample, integer snapshotEndSample, conststring32 manifestFileName,
		conststring32 pcmFileName, conststring32 wavFileName);
void praat_LongSound_writeVOTAudioSnapshot (LongSound longSound, integer objectId,
		integer snapshotStartSample, integer snapshotEndSample, conststring32 manifestFileName,
		conststring32 pcmFileName, conststring32 wavFileName);
void praat_VOT_analyseSnapshotAndWriteResult (conststring32 manifestFileName, conststring32 pcmFileName,
		integer targetStartSample, integer targetEndSample, integer contextStartSample,
		integer contextEndSample, integer alignedStartSample, integer alignedEndSample,
		conststring32 parametersJson, conststring32 resultFileName);

#endif
