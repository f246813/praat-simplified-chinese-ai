#ifndef _SegmentAcousticAnalysis_h_
#define _SegmentAcousticAnalysis_h_

#include "Sound.h"
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

struct SegmentInput {
	constSound samples { nullptr };   // Borrowed; never retained in AnalysisResult.
	SegmentMetadata metadata;
};

struct ParameterValue {
	std::u32string name;
	std::u32string value;
	std::u32string unit;
};

struct ParameterSnapshot {
	std::vector<ParameterValue> values;
	// Explicit subset whose equality is required before metric differences are meaningful.
	std::vector<std::u32string> compatibilityKeys;
};

struct TimeSeries {
	std::u32string metricId;
	std::u32string unit;
	std::vector<double> absoluteTimes;
	std::vector<double> values;
};

enum class AnalysisKind {
	VowelNasality,
	NasalConsonant,
	RSegment,
	VOT
};

// A side of the comparison editor is independent: changing its source or range
// must not implicitly change the other side.
struct SegmentAnalysisSelection {
	SegmentMetadata metadata;
	AnalysisKind analysisKind { AnalysisKind::VOT };
	double playbackStartTime { 0.0 };
	double playbackEndTime { 0.0 };
};

struct TargetReferenceSegment {
	SegmentAnalysisSelection target;
	std::optional<SegmentAnalysisSelection> reference;
};

void TargetReferenceSegment_setTarget (TargetReferenceSegment *pair, const SegmentAnalysisSelection &target);
void TargetReferenceSegment_setReference (TargetReferenceSegment *pair, const SegmentAnalysisSelection &reference);
void TargetReferenceSegment_clearReference (TargetReferenceSegment *pair);

enum class MetricStatus {
	measured,
	warning,
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
	double secondVoicingGapSeconds { 0.02 };
	double hnrSliceSeconds { 0.05 };
	double hnrMinimumSliceSeconds { 0.03 };
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
	AnalysisKind kind { AnalysisKind::VOT };
	SegmentMetadata source;
	ParameterSnapshot parameters;
	std::vector<MetricResult> metrics;
	std::vector<TimeSeries> curves;
};

struct MetricComparison {
	std::u32string metricId;
	std::u32string unit;
	std::optional<double> targetValue;
	std::optional<double> referenceValue;
	std::optional<double> difference;
	MetricStatus targetStatus { MetricStatus::unavailable };
	MetricStatus referenceStatus { MetricStatus::unavailable };
	std::u32string reason;
};

struct ComparisonResult {
	SegmentMetadata target;
	SegmentMetadata reference;
	std::vector<MetricComparison> rows;
};

ComparisonResult compareCompatibleMetrics (const AnalysisResult &target, const AnalysisResult &reference);
double votMilliseconds (double burstTime, double voicingTime);
AnalysisResult analyseVOT (const SegmentInput &input, std::optional<double> burstTime,
		std::optional<double> voicingTime, VOTBoundaryMode mode,
		const VOTCandidateSettings &candidateSettings = {});
void AnalysisResult_toTsv (const AnalysisResult &result, MelderString *output);

#endif
