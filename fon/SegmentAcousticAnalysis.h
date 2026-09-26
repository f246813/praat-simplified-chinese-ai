#ifndef _SegmentAcousticAnalysis_h_
#define _SegmentAcousticAnalysis_h_

#include "Sound.h"
#include "Harmonicity.h"
#include "MelderString.h"

#include <optional>
#include <string>
#include <vector>

enum class SourceKind {
	sound,
	longSound
};

struct SourceIdentity {
	std::optional<integer> objectId;
	std::u32string displayName;
	std::optional<std::u32string> filePath;
	SourceKind kind { SourceKind::sound };
	integer channels { 0 };
	double sampleRate { 0.0 };
};

struct UserMetadata {
	std::optional<std::u32string> language;
	std::optional<std::u32string> ipa;
	std::optional<std::u32string> speakerId;
	std::optional<std::u32string> neighboringVowel;
};

struct SegmentMetadata {
	SourceIdentity source;
	double startTime { 0.0 };
	double endTime { 0.0 };
	std::optional<double> burstTime;
	std::optional<double> voicingTime;
	UserMetadata annotation;
};

struct VOTDetectionScope {
	double contextStartTime { 0.0 };
	double contextEndTime { 0.0 };
	double targetStartTime { 0.0 };
	double targetEndTime { 0.0 };
	std::optional<double> alignedPhoneStartTime;
	std::optional<double> alignedPhoneEndTime;
};

struct SegmentInput {
	constSound samples { nullptr };   // Borrowed; never retained in AnalysisResult.
	SegmentMetadata metadata;
	std::optional<VOTDetectionScope> votScope;
};

struct ParameterValue {
	std::u32string name;
	std::u32string value;
	std::u32string unit;
};

struct ParameterSnapshot {
	std::vector<ParameterValue> values;
};

enum class MetricStatus {
	measured,
	warning,
	ambiguous,
	targetIncomplete,
	unavailable
};

enum class VOTBoundaryMode {
	manual,
	estimateCandidates
};

// Defaults preserve the existing AI estimator thresholds; all candidates remain subject to manual confirmation.
struct VOTCandidateSettings {
	double burstBandMinimumHz { 2000.0 };
	double burstBandMaximumHz { 8000.0 };
	double burstBandSmoothingHz { 100.0 };
	double burstThresholdDb { 6.0 };
	double intensityTimeStepSeconds { 0.001 };
	double pitchTimeStepSeconds { 0.002 };
	double pitchFloorHz { 75.0 };
	double pitchCeilingHz { 600.0 };
	integer maximumPitchCandidates { 15 };
	double pitchSilenceThreshold { 0.03 };
	double pitchVoicingThreshold { 0.45 };
	double pitchOctaveCost { 0.01 };
	double pitchOctaveJumpCost { 0.35 };
	double pitchVoicedUnvoicedCost { 0.14 };
	integer stableVoicedFrames { 3 };
	integer burstRiseLookbackFrames { 3 };
	integer burstRiseHoldFrames { 5 };
	double burstRiseHoldDropDb { 10.0 };
	double burstOnsetBacktrackDropDb { 8.0 };
	double burstCandidateSeparationSeconds { 0.04 };
	double maximumPositiveVotSeconds { 0.15 };
	double maximumPrevoicingLeadSeconds { 0.08 };
	double secondVoicingGapSeconds { 0.02 };
	double hnrSliceSeconds { 0.05 };
	double hnrMinimumSliceSeconds { 0.03 };
	double minimumHnrDb { -10.0 };
};

struct MetricResult {
	std::u32string id;
	std::u32string unit;
	std::optional<double> value;
	MetricStatus status { MetricStatus::unavailable };
	std::u32string reason;
};

struct AnalysisResult {
	int schemaVersion { 1 };
	SegmentMetadata source;
	ParameterSnapshot parameters;
	std::vector<MetricResult> metrics;
};

struct VOTDisplayData {
	VOTBoundaryMode mode { VOTBoundaryMode::estimateCandidates };
	std::optional<double> burstTime;
	std::optional<double> voicingTime;
	std::optional<double> valueMs;
	std::u32string failureReason;
};

double votMilliseconds (double burstTime, double voicingTime);
const MetricResult *AnalysisResult_findMetric (const AnalysisResult &result, conststring32 id);
VOTDisplayData AnalysisResult_toVOTDisplayData (const AnalysisResult &result, VOTBoundaryMode mode);
AnalysisResult analyseVOT (const SegmentInput &input, std::optional<double> burstTime,
		std::optional<double> voicingTime, VOTBoundaryMode mode,
		const VOTCandidateSettings &candidateSettings = {});
std::optional<double> maximumDefinedHnr (const constHarmonicity harmonicity);
void AnalysisResult_toTsv (const AnalysisResult &result, MelderString *output);
void AnalysisResult_toInfoSummary (const AnalysisResult &result, MelderString *output);
void writeSegmentAnalysisTsvAtomically (conststring32 resultFileName, conststring32 serialized);

#endif
