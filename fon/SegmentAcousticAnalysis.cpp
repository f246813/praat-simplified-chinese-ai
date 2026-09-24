#include "SegmentAcousticAnalysis.h"

#include <algorithm>
#include <utility>

namespace {

const ParameterValue *findParameter (const ParameterSnapshot &snapshot, const std::u32string &name) {
	const auto found = std::find_if (snapshot.values.begin(), snapshot.values.end(), [&] (const ParameterValue &value) {
		return value.name == name;
	});
	return found == snapshot.values.end() ? nullptr : & *found;
}

bool hasCompatibilityKey (const ParameterSnapshot &snapshot, const std::u32string &name) {
	return std::find (snapshot.compatibilityKeys.begin(), snapshot.compatibilityKeys.end(), name) != snapshot.compatibilityKeys.end();
}

std::u32string parameterCompatibilityReason (const ParameterSnapshot &target, const ParameterSnapshot &reference) {
	for (const std::u32string &key : target.compatibilityKeys) {
		if (! hasCompatibilityKey (reference, key))
			return U"incompatible parameters: missing " + key;
		const ParameterValue *targetValue = findParameter (target, key);
		const ParameterValue *referenceValue = findParameter (reference, key);
		if (! targetValue || ! referenceValue)
			return U"incompatible parameters: missing value for " + key;
		if (targetValue -> value != referenceValue -> value || targetValue -> unit != referenceValue -> unit)
			return U"incompatible parameters: " + key;
	}
	for (const std::u32string &key : reference.compatibilityKeys) {
		if (! hasCompatibilityKey (target, key))
			return U"incompatible parameters: missing " + key;
	}
	return {};
}

const MetricResult *findMetric (const AnalysisResult &result, const std::u32string &metricId) {
	const auto found = std::find_if (result.metrics.begin(), result.metrics.end(), [&] (const MetricResult &metric) {
		return metric.id == metricId;
	});
	return found == result.metrics.end() ? nullptr : & *found;
}

void addComparisonRow (	ComparisonResult &comparison,
		const AnalysisResult &target, const AnalysisResult &reference,
		const MetricResult *targetMetric, const MetricResult *referenceMetric,
		const std::u32string &parameterReason
) {
	const MetricResult *identityMetric = targetMetric ? targetMetric : referenceMetric;
	MetricComparison row;
	row.metricId = identityMetric -> id;
	row.unit = targetMetric ? targetMetric -> unit : referenceMetric -> unit;
	if (targetMetric) {
		row.targetValue = targetMetric -> value;
		row.targetStatus = targetMetric -> status;
	}
	if (referenceMetric) {
		row.referenceValue = referenceMetric -> value;
		row.referenceStatus = referenceMetric -> status;
	}

	if (! targetMetric || ! referenceMetric) {
		row.reason = ! targetMetric ? U"metric is missing from target analysis" : U"metric is missing from reference analysis";
	} else if (target.kind != reference.kind) {
		row.reason = U"analysis kinds differ";
	} else if (targetMetric -> unit != referenceMetric -> unit) {
		row.reason = U"metric units differ";
	} else if (! parameterReason.empty()) {
		row.reason = parameterReason;
	} else if (! targetMetric -> value || ! referenceMetric -> value) {
		if (! targetMetric -> value) {
			row.reason = U"target unavailable";
			if (! targetMetric -> reason.empty())
				row.reason += U": " + targetMetric -> reason;
		}
		if (! referenceMetric -> value) {
			if (! row.reason.empty())
				row.reason += U"; ";
			row.reason += U"reference unavailable";
			if (! referenceMetric -> reason.empty())
				row.reason += U": " + referenceMetric -> reason;
		}
	} else {
		row.difference = targetMetric -> value.value() - referenceMetric -> value.value();
	}
	comparison.rows.push_back (std::move (row));
}

void appendTsvField (MelderString *output, const std::u32string &value) {
	for (const char32 character : value) {
		if (character == U'\\')
			MelderString_append (output, U"\\\\");
		else if (character == U'\t')
			MelderString_append (output, U"\\t");
		else if (character == U'\n')
			MelderString_append (output, U"\\n");
		else if (character == U'\r')
			MelderString_append (output, U"\\r");
		else
			MelderString_appendCharacter (output, character);
	}
}

conststring32 analysisKindName (AnalysisKind kind) {
	switch (kind) {
		case AnalysisKind::VowelNasality: return U"VowelNasality";
		case AnalysisKind::NasalConsonant: return U"NasalConsonant";
		case AnalysisKind::RSegment: return U"RSegment";
		case AnalysisKind::VOT: return U"VOT";
	}
	return U"Unknown";
}

conststring32 metricStatusName (MetricStatus status) {
	switch (status) {
		case MetricStatus::measured: return U"measured";
		case MetricStatus::warning: return U"warning";
		case MetricStatus::unavailable: return U"unavailable";
	}
	return U"unavailable";
}

} // namespace

ComparisonResult compareCompatibleMetrics (const AnalysisResult &target, const AnalysisResult &reference) {
	ComparisonResult result;
	result.target = target.source;
	result.reference = reference.source;
	const std::u32string parameterReason = parameterCompatibilityReason (target.parameters, reference.parameters);
	for (const MetricResult &targetMetric : target.metrics) {
		addComparisonRow (result, target, reference, & targetMetric, findMetric (reference, targetMetric.id), parameterReason);
	}
	for (const MetricResult &referenceMetric : reference.metrics) {
		if (! findMetric (target, referenceMetric.id))
			addComparisonRow (result, target, reference, nullptr, & referenceMetric, parameterReason);
	}
	return result;
}

void AnalysisResult_toTsv (const AnalysisResult &result, MelderString *output) {
	MelderString_empty (output);
	MelderString_append (output, U"schema_version\tanalysis_kind\tmetric_id\tvalue\tunit\tstatus\treason\n");
	for (const MetricResult &metric : result.metrics) {
		MelderString_append (output, result.schemaVersion, U"\t", analysisKindName (result.kind), U"\t");
		appendTsvField (output, metric.id);
		MelderString_appendCharacter (output, U'\t');
		if (metric.status != MetricStatus::unavailable && metric.value)
			MelderString_append (output, Melder_double (metric.value.value()));
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, metric.unit);
		MelderString_append (output, U"\t", metricStatusName (metric.status), U"\t");
		appendTsvField (output, metric.reason);
		MelderString_appendCharacter (output, U'\n');
	}
}
