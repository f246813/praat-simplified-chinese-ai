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
	UserMetadata annotation;
};

struct SegmentInput {
	const Sound *samples { nullptr };   // Borrowed; never retained in AnalysisResult.
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

enum class MetricStatus {
	measured,
	warning,
	unavailable
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
void AnalysisResult_toTsv (const AnalysisResult &result, MelderString *output);

#endif
