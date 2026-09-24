#include "SegmentAcousticAnalysis.h"

#include "Sound_and_Spectrum.h"
#include "Sound_to_Harmonicity.h"
#include "Sound_to_Intensity.h"
#include "Sound_to_Pitch.h"
#include "melder_app.h"
#include "melder_atof.h"
#include "melder_files.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <limits>
#include <string_view>

#if defined (_WIN32)
	#include <process.h>
#else
	#include <unistd.h>
#endif

void TargetReferenceSegment_setTarget (TargetReferenceSegment *pair, const SegmentAnalysisSelection &target) {
	Melder_assert (pair);
	pair -> target = target;
}

void TargetReferenceSegment_setReference (TargetReferenceSegment *pair, const SegmentAnalysisSelection &reference) {
	Melder_assert (pair);
	pair -> reference = reference;
}

void TargetReferenceSegment_clearReference (TargetReferenceSegment *pair) {
	Melder_assert (pair);
	pair -> reference.reset();
}
#include <cmath>
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

conststring32 analysisKindName (AnalysisKind kind);

std::optional<double> requestedMaximumFrequency (const ParameterSnapshot &snapshot) {
	static const std::u32string_view keys [] { U"maximumFrequency", U"maximumFrequencyHz", U"maxFrequency", U"bandHighHz", U"bandMaximumHz" };
	for (const ParameterValue &parameter : snapshot.values) {
		if (parameter.unit != U"Hz")
			continue;
		for (const std::u32string_view key : keys) {
			if (parameter.name == key) {
				const double value = Melder_atof (parameter.value.c_str());
				if (std::isfinite (value) && value > 0.0)
					return value;
			}
		}
	}
	return {};
}

std::u32string nyquistCompatibilityReason (const SegmentMetadata &target, const SegmentMetadata &reference,
		const ParameterSnapshot &targetParameters, const ParameterSnapshot &referenceParameters)
{
	const std::optional<double> targetMaximum = requestedMaximumFrequency (targetParameters);
	const std::optional<double> referenceMaximum = requestedMaximumFrequency (referenceParameters);
	if (! targetMaximum && ! referenceMaximum)
		return {};
	const double requiredMaximum = std::max (targetMaximum.value_or (0.0), referenceMaximum.value_or (0.0));
	if (target.source.sampleRate > 0.0 && target.source.sampleRate * 0.5 < requiredMaximum)
		return U"target Nyquist (" + std::u32string (Melder_double (target.source.sampleRate * 0.5)) +
			U" Hz) is below requested maximum frequency (" + std::u32string (Melder_double (requiredMaximum)) + U" Hz)";
	if (reference.source.sampleRate > 0.0 && reference.source.sampleRate * 0.5 < requiredMaximum)
		return U"reference Nyquist (" + std::u32string (Melder_double (reference.source.sampleRate * 0.5)) +
			U" Hz) is below requested maximum frequency (" + std::u32string (Melder_double (requiredMaximum)) + U" Hz)";
	return {};
}

std::u32string burstBandCompatibilityReason (const SegmentMetadata &target, const SegmentMetadata &reference,
		const ParameterSnapshot &targetParameters, const ParameterSnapshot &referenceParameters)
{
	const ParameterValue *targetPath = findParameter (targetParameters, U"burstDetectionPath");
	const ParameterValue *referencePath = findParameter (referenceParameters, U"burstDetectionPath");
	if (! targetPath || ! referencePath)
		return {};
	if (targetPath -> value != referencePath -> value)
		return U"incompatible VOT burst detection paths (" + targetPath -> value + U" vs " + referencePath -> value + U")";
	if (targetPath -> value != U"high-band")
		return {};
	const ParameterValue *targetMaximumParameter = findParameter (targetParameters, U"burstBandMaximumHz");
	const ParameterValue *referenceMaximumParameter = findParameter (referenceParameters, U"burstBandMaximumHz");
	if (! targetMaximumParameter || ! referenceMaximumParameter)
		return U"incompatible VOT burst band settings";
	const double requiredMaximum = std::max (Melder_atof (targetMaximumParameter -> value.c_str()),
		Melder_atof (referenceMaximumParameter -> value.c_str()));
	if (target.source.sampleRate > 0.0 && target.source.sampleRate * 0.5 < requiredMaximum)
		return U"target Nyquist does not cover the VOT burst detection band";
	if (reference.source.sampleRate > 0.0 && reference.source.sampleRate * 0.5 < requiredMaximum)
		return U"reference Nyquist does not cover the VOT burst detection band";
	return {};
}

bool burstDependentMetric (const std::u32string &metricId) {
	return metricId == U"burst_time_candidate" || metricId == U"burst_rise_db" ||
		metricId == U"vot_candidate_s" || metricId == U"vot_candidate_ms";
}

std::u32string sampleRateWarning (const SegmentMetadata &target, const SegmentMetadata &reference) {
	if (target.source.sampleRate <= 0.0 || reference.source.sampleRate <= 0.0 ||
			std::abs (target.source.sampleRate - reference.source.sampleRate) < 1.0e-9)
		return {};
	return U"different sample rates (" + std::u32string (Melder_double (target.source.sampleRate)) + U" vs " +
		std::u32string (Melder_double (reference.source.sampleRate)) + U" Hz); measurements retain their original rates";
}

void addComparisonRow (	ComparisonResult &comparison,
		const AnalysisResult &target, const AnalysisResult &reference,
		const MetricResult *targetMetric, const MetricResult *referenceMetric,
		const std::u32string &parameterReason, const std::u32string &bandwidthReason, const std::u32string &burstReason,
		const std::u32string &rateWarning
) {
	const MetricResult *identityMetric = targetMetric ? targetMetric : referenceMetric;
	MetricComparison row;
	row.metricId = identityMetric -> id;
	row.unit = targetMetric ? targetMetric -> unit : referenceMetric -> unit;
	if (targetMetric) {
		row.targetValue = targetMetric -> value;
		row.targetStatus = targetMetric -> status;
		row.targetReason = targetMetric -> reason;
	}
	if (referenceMetric) {
		row.referenceValue = referenceMetric -> value;
		row.referenceStatus = referenceMetric -> status;
		row.referenceReason = referenceMetric -> reason;
	}
	row.warning = rateWarning;

	if (! targetMetric || ! referenceMetric) {
		row.reason = ! targetMetric ? U"metric is missing from target analysis" : U"metric is missing from reference analysis";
	} else if (target.kind != reference.kind) {
		row.reason = U"analysis kinds differ";
	} else if (targetMetric -> unit != referenceMetric -> unit) {
		row.reason = U"metric units differ";
	} else if (! parameterReason.empty()) {
		row.reason = parameterReason;
	} else if (! bandwidthReason.empty()) {
		row.reason = bandwidthReason;
	} else if (burstDependentMetric (row.metricId) && ! burstReason.empty()) {
		row.reason = burstReason;
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

void appendTsvOptionalText (MelderString *output, const std::optional<std::u32string> &value) {
	if (value)
		appendTsvField (output, value.value());
}

void appendTsvOptionalInteger (MelderString *output, const std::optional<integer> &value) {
	if (value)
		MelderString_append (output, value.value());
}

void appendTsvOptionalNumber (MelderString *output, const std::optional<double> &value) {
	if (value)
		MelderString_append (output, Melder_double (value.value()));
}

void appendTsvParameterSnapshot (MelderString *output, const ParameterSnapshot &snapshot) {
	std::u32string encoded;
	for (const ParameterValue &parameter : snapshot.values) {
		if (! encoded.empty())
			encoded += U"; ";
		encoded += parameter.name + U"=" + parameter.value;
		if (! parameter.unit.empty())
			encoded += U" " + parameter.unit;
	}
	appendTsvField (output, encoded);
}

void appendTsvNumberVector (MelderString *output, const std::vector<double> &values) {
	std::u32string encoded;
	for (const double value : values) {
		if (! encoded.empty())
			encoded += U"; ";
	encoded += Melder_double (value);
	}
	appendTsvField (output, encoded);
}

const FrequencyOverlay *findFrequencyOverlay (const ComparisonResult &result, const std::u32string &metricId) {
	const auto found = std::find_if (result.frequencyOverlays.begin(), result.frequencyOverlays.end(), [&] (const FrequencyOverlay &overlay) {
		return overlay.metricId == metricId;
	});
	return found == result.frequencyOverlays.end() ? nullptr : & *found;
}

void appendTsvSourceMetadata (MelderString *output, const SegmentMetadata &metadata,
		const ParameterSnapshot &parameters, AnalysisKind kind)
{
	appendTsvField (output, metadata.source.displayName);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalInteger (output, metadata.source.objectId);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.source.filePath);
	MelderString_append (output, U"\t", Melder_double (metadata.startTime), U"\t", Melder_double (metadata.endTime), U"\t",
		Melder_double (metadata.endTime - metadata.startTime), U"\t", Melder_double (metadata.source.sampleRate), U"\t",
		metadata.source.channels, U"\t", metadata.source.kind == SourceKind::sound ? U"Sound" : U"LongSound", U"\t",
		analysisKindName (kind), U"\t");
	appendTsvParameterSnapshot (output, parameters);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.annotation.language);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.annotation.ipa);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.annotation.speakerId);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.annotation.neighboringVowel);
}

double interpolateAt (const FrequencySeries &curve, double frequency) {
	auto upper = std::upper_bound (curve.frequencyHz.begin(), curve.frequencyHz.end(), frequency);
	if (upper == curve.frequencyHz.begin())
		return curve.values.front();
	if (upper == curve.frequencyHz.end())
		return curve.values.back();
	const size_t upperIndex = (size_t) (upper - curve.frequencyHz.begin());
	const size_t lowerIndex = upperIndex - 1;
	const double fraction = (frequency - curve.frequencyHz [lowerIndex]) /
		(curve.frequencyHz [upperIndex] - curve.frequencyHz [lowerIndex]);
	return curve.values [lowerIndex] + fraction * (curve.values [upperIndex] - curve.values [lowerIndex]);
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

std::u32string numberAsText (double value) {
	return std::u32string (Melder_double (value));
}

void addParameter (AnalysisResult &result, conststring32 name, double value, conststring32 unit, bool affectsCompatibility = true) {
	result.parameters.values.push_back ({ name, numberAsText (value), unit });
	if (affectsCompatibility)
		result.parameters.compatibilityKeys.emplace_back (name);
}

void addTextParameter (AnalysisResult &result, conststring32 name, conststring32 value, conststring32 unit = U"", bool affectsCompatibility = true) {
	result.parameters.values.push_back ({ name, value, unit });
	if (affectsCompatibility)
		result.parameters.compatibilityKeys.emplace_back (name);
}

void addMetric (AnalysisResult &result, conststring32 id, conststring32 unit,
		std::optional<double> value, MetricStatus status, conststring32 reason)
{
	result.metrics.push_back ({ id, unit, value, status, reason });
}

struct EnvelopeRise {
	std::optional<double> onset;
	double riseDb { 0.0 };
};

EnvelopeRise findSteepestEnvelopeRise (constIntensity envelope, double minimumTime, double maximumTime,
		const VOTCandidateSettings &settings)
{
	EnvelopeRise result;
	double bestRise = -1000.0;
	integer bestFrame = 0;
	for (integer frame = 1; frame <= envelope -> nx; frame ++) {
		const double frameTime = envelope -> x1 + (frame - 1) * envelope -> dx;
		const integer lookbackFrame = frame - settings.burstRiseLookbackFrames;
		if (lookbackFrame < 1 || frameTime < minimumTime || frameTime > maximumTime)
			continue;
		const double lookbackTime = envelope -> x1 + (lookbackFrame - 1) * envelope -> dx;
		if (lookbackTime < minimumTime)
			continue;
		const double currentValue = envelope -> z [1] [frame];
		const double previousValue = envelope -> z [1] [lookbackFrame];
		double laterValue = currentValue;
		const integer holdFrame = frame + settings.burstRiseHoldFrames;
		if (holdFrame <= envelope -> nx)
			laterValue = envelope -> z [1] [holdFrame];
		const double rise = currentValue - previousValue;
		if (laterValue >= currentValue - settings.burstRiseHoldDropDb && rise > bestRise) {
			bestRise = rise;
			bestFrame = frame;
		}
	}
	if (bestFrame == 0)
		return result;

	result.riseDb = bestRise;
	result.onset = envelope -> x1 + (bestFrame - 1) * envelope -> dx;
	const double referenceValue = envelope -> z [1] [bestFrame];
	for (integer frame = bestFrame - 1; frame >= 1; frame --) {
		const double frameTime = envelope -> x1 + (frame - 1) * envelope -> dx;
		if (frameTime < minimumTime || envelope -> z [1] [frame] < referenceValue - settings.burstOnsetBacktrackDropDb)
			break;
		result.onset = frameTime;
	}
	return result;
}

struct BurstDetection {
	std::optional<double> time;
	double riseDb { 0.0 };
	std::u32string band;
	std::u32string reason;
};

BurstDetection detectBurst (Sound sound, double minimumTime, double maximumTime, const VOTCandidateSettings &settings) {
	BurstDetection result;
	EnvelopeRise highBandRise;
	const double nyquistFrequency = 0.5 / sound -> dx;
	if (nyquistFrequency >= settings.burstBandMaximumHz) {
		try {
			autoSound highBandSound = Sound_filter_passHannBand (sound,
				settings.burstBandMinimumHz, settings.burstBandMaximumHz, settings.burstBandSmoothingHz);
			autoIntensity highBandEnvelope = Sound_to_Intensity (
				highBandSound.get(), 2000.0, settings.intensityTimeStepSeconds, true);
			highBandRise = findSteepestEnvelopeRise (highBandEnvelope.get(), minimumTime, maximumTime, settings);
		} catch (MelderError) {
			Melder_clearError ();
		}
	}
	if (highBandRise.onset && highBandRise.riseDb >= settings.burstThresholdDb) {
		result.time = highBandRise.onset;
		result.riseDb = highBandRise.riseDb;
		result.band = U"2–8 kHz";
		return result;
	}

	try {
		autoIntensity broadbandEnvelope = Sound_to_Intensity (sound, 1000.0, settings.intensityTimeStepSeconds, true);
		const EnvelopeRise broadbandRise = findSteepestEnvelopeRise (
			broadbandEnvelope.get(), minimumTime, maximumTime, settings);
		if (broadbandRise.onset && broadbandRise.riseDb >= settings.burstThresholdDb) {
			result.time = broadbandRise.onset;
			result.riseDb = broadbandRise.riseDb;
			result.band = U"full band";
			return result;
		}
	} catch (MelderError) {
		Melder_clearError ();
	}
	result.reason = U"No sustained energy rise reached the ";
	result.reason += Melder_double (settings.burstThresholdDb);
	result.reason += U" dB threshold in the high-frequency or full-band envelope.";
	return result;
}

void validateVOTCandidateSettings (const VOTCandidateSettings &settings) {
	if (! std::isfinite (settings.burstThresholdDb) || settings.burstThresholdDb < 3.0 || settings.burstThresholdDb > 30.0)
		Melder_throw (U"burstThresholdDb must be between 3 and 30 dB.");
	if (! std::isfinite (settings.pitchFloorHz) || settings.pitchFloorHz < 40.0 || settings.pitchFloorHz > 500.0)
		Melder_throw (U"pitchFloorHz must be between 40 and 500 Hz.");
	if (! std::isfinite (settings.pitchCeilingHz) || settings.pitchCeilingHz <= settings.pitchFloorHz)
		Melder_throw (U"pitchCeilingHz must be higher than pitchFloorHz.");
	if (! std::isfinite (settings.burstBandMinimumHz) || ! std::isfinite (settings.burstBandMaximumHz) ||
			settings.burstBandMinimumHz < 0.0 || settings.burstBandMaximumHz <= settings.burstBandMinimumHz ||
			! std::isfinite (settings.burstBandSmoothingHz) || settings.burstBandSmoothingHz < 0.0)
		Melder_throw (U"The VOT burst frequency band and smoothing must be valid.");
	if (settings.maximumPitchCandidates < 2 || settings.stableVoicedFrames < 1)
		Melder_throw (U"VOT pitch settings require at least two candidates and one stable voiced frame.");
	if (! std::isfinite (settings.intensityTimeStepSeconds) || settings.intensityTimeStepSeconds <= 0.0 ||
			! std::isfinite (settings.pitchTimeStepSeconds) || settings.pitchTimeStepSeconds <= 0.0)
		Melder_throw (U"VOT analysis time steps must be positive and finite.");
}

AnalysisResult estimateVOTCandidates (const SegmentInput &input, const VOTCandidateSettings &settings) {
	validateVOTCandidateSettings (settings);
	if (! std::isfinite (input.metadata.startTime) || ! std::isfinite (input.metadata.endTime) ||
			input.metadata.startTime >= input.metadata.endTime || input.metadata.startTime < input.samples -> xmin ||
			input.metadata.endTime > input.samples -> xmax)
		Melder_throw (U"Candidate estimation requires a valid segment inside the Sound time domain.");

	const double minimumTime = input.metadata.startTime;
	const double maximumTime = input.metadata.endTime;
	autoSound extractedSegment = Sound_extractPart (const_cast<Sound> (input.samples), minimumTime, maximumTime,
		kSound_windowShape::RECTANGULAR, 1.0, true);
	Sound sound = extractedSegment.get();
	const BurstDetection burst = detectBurst (sound, minimumTime, maximumTime, settings);
	autoPitch pitch = Sound_to_Pitch_rawAc (sound,
		settings.pitchTimeStepSeconds, settings.pitchFloorHz, settings.pitchCeilingHz,
		settings.maximumPitchCandidates, false, settings.pitchSilenceThreshold, settings.pitchVoicingThreshold,
		settings.pitchOctaveCost, settings.pitchOctaveJumpCost, settings.pitchVoicedUnvoicedCost);

	std::optional<double> firstVoicedTime;
	std::optional<double> voicingTime;
	std::optional<double> secondVoicingTime;
	double voicingOnsetF0 = 0.0;
	double runStart = -1.0;
	double runStartF0 = 0.0;
	double lastVoicedTime = -1.0;
	double secondRunStart = -1.0;
	integer voicedRun = 0;
	bool rangeStartsVoiced = false;

	for (integer frame = 1; frame <= pitch -> nx; frame ++) {
		const double frameTime = pitch -> x1 + (frame - 1) * pitch -> dx;
		if (frameTime < minimumTime || frameTime > maximumTime)
			continue;
		const double frequency = pitch -> frames [frame]. candidates [1]. frequency;
		if (frequency > 0.0) {
			if (! firstVoicedTime) {
				firstVoicedTime = frameTime;
				rangeStartsVoiced = frameTime <= minimumTime + 0.01;
			}
			voicedRun ++;
			if (voicedRun == 1) {
				runStart = frameTime;
				runStartF0 = frequency;
			}
			if (! voicingTime && voicedRun >= settings.stableVoicedFrames && ! rangeStartsVoiced) {
				const bool runAfterBurst = ! burst.time || runStart >= burst.time.value();
				// A pitch frame centred on the release can look voiced before the actual vowel begins.
				const double minimumPrevoicingLead = settings.stableVoicedFrames * settings.pitchTimeStepSeconds;
				const bool runSpansBurst = burst.time && runStart <= burst.time.value() - minimumPrevoicingLead &&
					frameTime >= burst.time.value();
				if (runAfterBurst || runSpansBurst) {
					voicingTime = runStart;
					voicingOnsetF0 = runStartF0;
				}
			}
			if (secondRunStart >= 0.0 && ! secondVoicingTime)
				secondVoicingTime = secondRunStart;
			else if (lastVoicedTime >= 0.0 && voicingTime && frameTime - lastVoicedTime >= settings.secondVoicingGapSeconds)
				secondRunStart = frameTime;
			lastVoicedTime = frameTime;
		} else {
			voicedRun = 0;
			secondRunStart = -1.0;
		}
	}

	AnalysisResult result;
	result.kind = AnalysisKind::VOT;
	result.source = input.metadata;
	addTextParameter (result, U"boundaryMode", U"estimateCandidates");
	addTextParameter (result, U"burstDetectionPath",
		0.5 / sound -> dx >= settings.burstBandMaximumHz ? U"high-band" : U"full-band-fallback", U"", false);
	addParameter (result, U"burstBandMinimumHz", settings.burstBandMinimumHz, U"Hz");
	addParameter (result, U"burstBandMaximumHz", settings.burstBandMaximumHz, U"Hz");
	addParameter (result, U"burstBandSmoothingHz", settings.burstBandSmoothingHz, U"Hz");
	addParameter (result, U"burstThresholdDb", settings.burstThresholdDb, U"dB");
	addParameter (result, U"intensityTimeStepSeconds", settings.intensityTimeStepSeconds, U"s");
	addParameter (result, U"pitchTimeStepSeconds", settings.pitchTimeStepSeconds, U"s");
	addParameter (result, U"pitchFloorHz", settings.pitchFloorHz, U"Hz");
	addParameter (result, U"pitchCeilingHz", settings.pitchCeilingHz, U"Hz");
	addParameter (result, U"maximumPitchCandidates", (double) settings.maximumPitchCandidates, U"candidates");
	addParameter (result, U"pitchSilenceThreshold", settings.pitchSilenceThreshold, U"relative");
	addParameter (result, U"pitchVoicingThreshold", settings.pitchVoicingThreshold, U"relative");
	addParameter (result, U"pitchOctaveCost", settings.pitchOctaveCost, U"cost");
	addParameter (result, U"pitchOctaveJumpCost", settings.pitchOctaveJumpCost, U"cost");
	addParameter (result, U"pitchVoicedUnvoicedCost", settings.pitchVoicedUnvoicedCost, U"cost");
	addParameter (result, U"stableVoicedFrames", (double) settings.stableVoicedFrames, U"frames");
	addParameter (result, U"burstRiseLookbackFrames", (double) settings.burstRiseLookbackFrames, U"frames");
	addParameter (result, U"burstRiseHoldFrames", (double) settings.burstRiseHoldFrames, U"frames");
	addParameter (result, U"burstRiseHoldDropDb", settings.burstRiseHoldDropDb, U"dB");
	addParameter (result, U"burstOnsetBacktrackDropDb", settings.burstOnsetBacktrackDropDb, U"dB");
	addParameter (result, U"secondVoicingGapSeconds", settings.secondVoicingGapSeconds, U"s");
	addParameter (result, U"hnrSliceSeconds", settings.hnrSliceSeconds, U"s");
	addParameter (result, U"hnrMinimumSliceSeconds", settings.hnrMinimumSliceSeconds, U"s");

	if (burst.time) {
		std::u32string reason = U"Candidate from ";
		reason += burst.band;
		reason += U" envelope; inspect and confirm manually.";
		addMetric (result, U"burst_time_candidate", U"s", burst.time, MetricStatus::warning, reason.c_str());
		addMetric (result, U"burst_rise_db", U"dB", burst.riseDb, MetricStatus::measured, burst.band.c_str());
	} else {
		addMetric (result, U"burst_time_candidate", U"s", {}, MetricStatus::unavailable, burst.reason.c_str());
		addMetric (result, U"burst_rise_db", U"dB", {}, MetricStatus::unavailable, burst.reason.c_str());
	}

	if (rangeStartsVoiced) {
		voicingTime.reset ();
		addMetric (result, U"voicing_time_candidate", U"s", {}, MetricStatus::unavailable,
			U"The selected range begins within 10 ms of stable voicing; include the closure or choose a later segment.");
		addMetric (result, U"voicing_f0_hz", U"Hz", {}, MetricStatus::unavailable,
			U"The selected range begins with voicing, so its onset is outside the selected range.");
	} else if (voicingTime) {
		const bool prevoicing = burst.time && voicingTime.value() < burst.time.value();
		const conststring32 reason = prevoicing ?
			U"Stable autocorrelation voicing continues across the release; this negative VOT candidate needs manual confirmation." :
			U"Autocorrelation frequency persists for the configured stable-frame run; inspect and confirm manually.";
		addMetric (result, U"voicing_time_candidate", U"s", voicingTime, MetricStatus::warning, reason);
		addMetric (result, U"voicing_f0_hz", U"Hz", voicingOnsetF0, MetricStatus::measured, U"Frequency at the start of the stable voiced run.");
	} else {
		addMetric (result, U"voicing_time_candidate", U"s", {}, MetricStatus::unavailable,
			U"No stable run of autocorrelation-pitched frames was found after or across the release.");
		addMetric (result, U"voicing_f0_hz", U"Hz", {}, MetricStatus::unavailable,
			U"No stable voiced run was available for an onset frequency.");
	}

	std::optional<double> hnrMaximum;
	if (voicingTime && ! rangeStartsVoiced) {
		const double hnrEnd = std::min (voicingTime.value() + settings.hnrSliceSeconds, sound -> xmax);
		if (hnrEnd - voicingTime.value() >= settings.hnrMinimumSliceSeconds) {
			try {
				autoSound hnrSlice = Sound_extractPart (sound, voicingTime.value(), hnrEnd,
					kSound_windowShape::RECTANGULAR, 1.0, false);
				autoHarmonicity hnr = Sound_to_Harmonicity_cc (hnrSlice.get(), settings.pitchTimeStepSeconds,
					settings.pitchFloorHz, 0.1, 1.0);
				hnrMaximum = maximumDefinedHnr (hnr.get());
			} catch (MelderError) {
				Melder_clearError ();
			}
		}
	}
	if (hnrMaximum)
		addMetric (result, U"hnr_max_db", U"dB", hnrMaximum, MetricStatus::measured, U"Maximum HNR within the short post-onset slice.");
	else
		addMetric (result, U"hnr_max_db", U"dB", {}, MetricStatus::unavailable, U"The short post-onset slice was too short or HNR analysis failed.");

	if (secondVoicingTime)
		addMetric (result, U"second_voicing_time_candidate", U"s", secondVoicingTime, MetricStatus::warning,
			U"A later voiced segment follows a gap of at least 20 ms; narrow the analysis range.");
	else
		addMetric (result, U"second_voicing_time_candidate", U"s", {}, MetricStatus::unavailable,
			U"No second voiced run separated by the configured gap was found.");

	if (burst.time && voicingTime && ! rangeStartsVoiced) {
		const double votSeconds = voicingTime.value() - burst.time.value();
		addMetric (result, U"vot_candidate_s", U"s", votSeconds, MetricStatus::warning,
			U"Difference of estimated candidates; confirm both boundaries before reporting VOT.");
		addMetric (result, U"vot_candidate_ms", U"ms", votMilliseconds (burst.time.value(), voicingTime.value()),
			MetricStatus::warning, U"Difference of estimated candidates; confirm both boundaries before reporting VOT.");
	} else {
		const std::u32string reason = ! burst.time ? U"Burst candidate unavailable: " + burst.reason :
			U"Voicing candidate unavailable for the selected range.";
		addMetric (result, U"vot_candidate_s", U"s", {}, MetricStatus::unavailable, reason.c_str());
		addMetric (result, U"vot_candidate_ms", U"ms", {}, MetricStatus::unavailable, reason.c_str());
	}
	return result;
}

} // namespace

std::optional<double> maximumDefinedHnr (constHarmonicity harmonicity) {
	if (! harmonicity)
		return {};
	std::optional<double> maximum;
	for (integer frame = 1; frame <= harmonicity -> nx; frame ++) {
		const double value = harmonicity -> z [1] [frame];
		if (isundef (value) || ! std::isfinite (value) || value < -150.0)
			continue;
		if (! maximum || value > maximum.value())
			maximum = value;
	}
	return maximum;
}

ComparisonResult compareCompatibleMetrics (const AnalysisResult &target, const AnalysisResult &reference) {
	ComparisonResult result;
	result.target = target.source;
	result.reference = reference.source;
	result.schemaVersion = std::max (target.schemaVersion, reference.schemaVersion);
	result.targetKind = target.kind;
	result.referenceKind = reference.kind;
	result.targetParameters = target.parameters;
	result.referenceParameters = reference.parameters;
	const std::u32string parameterReason = parameterCompatibilityReason (target.parameters, reference.parameters);
	const std::u32string bandwidthReason = nyquistCompatibilityReason (target.source, reference.source,
		target.parameters, reference.parameters);
	const std::u32string burstReason = burstBandCompatibilityReason (target.source, reference.source,
		target.parameters, reference.parameters);
	const std::u32string rateWarning = sampleRateWarning (target.source, reference.source);
	for (const MetricResult &targetMetric : target.metrics) {
		addComparisonRow (result, target, reference, & targetMetric, findMetric (reference, targetMetric.id),
			parameterReason, bandwidthReason, burstReason, rateWarning);
	}
	for (const MetricResult &referenceMetric : reference.metrics) {
		if (! findMetric (target, referenceMetric.id))
			addComparisonRow (result, target, reference, nullptr, & referenceMetric, parameterReason, bandwidthReason, burstReason, rateWarning);
	}
	for (const FrequencySeries &targetCurve : target.frequencyCurves) {
		const auto referenceCurve = std::find_if (reference.frequencyCurves.begin(), reference.frequencyCurves.end(),
			[&] (const FrequencySeries &candidate) {
				return candidate.metricId == targetCurve.metricId && candidate.unit == targetCurve.unit;
			});
		if (referenceCurve == reference.frequencyCurves.end())
			continue;
		if (target.kind != reference.kind || ! parameterReason.empty() || ! bandwidthReason.empty()) {
			FrequencyOverlay unavailable;
			unavailable.metricId = targetCurve.metricId;
			unavailable.unit = targetCurve.unit;
			unavailable.reason = target.kind != reference.kind ? U"analysis kinds differ" :
				! parameterReason.empty() ? parameterReason : bandwidthReason;
			result.frequencyOverlays.push_back (std::move (unavailable));
			continue;
		}
		try {
			result.frequencyOverlays.push_back (interpolateCommonFrequencyGrid (targetCurve, target.source.source.sampleRate,
				* referenceCurve, reference.source.source.sampleRate));
		} catch (MelderError) {
			FrequencyOverlay unavailable;
			unavailable.metricId = targetCurve.metricId;
			unavailable.unit = targetCurve.unit;
			unavailable.reason = Melder_getError();
			result.frequencyOverlays.push_back (std::move (unavailable));
			Melder_clearError ();
		}
	}
	return result;
}

NormalizedTimeSeries normalizeTimeSeriesForOverlay (const TimeSeries &curve, const SegmentMetadata &segment) {
	Melder_require (std::isfinite (segment.startTime) && std::isfinite (segment.endTime) && segment.startTime < segment.endTime,
		U"A time-series overlay requires a valid segment interval.");
	Melder_require (curve.absoluteTimes.size() == curve.values.size() && ! curve.values.empty(),
		U"A time-series overlay requires one value for every absolute time.");
	NormalizedTimeSeries result;
	result.metricId = curve.metricId;
	result.unit = curve.unit;
	result.values = curve.values;
	result.relativePercent.reserve (curve.absoluteTimes.size());
	double previousTime = - std::numeric_limits<double>::infinity();
	for (const double time : curve.absoluteTimes) {
		Melder_require (std::isfinite (time) && time >= segment.startTime && time <= segment.endTime && time > previousTime,
			U"Time-series points must be ordered and stay inside the recorded segment interval.");
		result.relativePercent.push_back (100.0 * (time - segment.startTime) / (segment.endTime - segment.startTime));
		previousTime = time;
	}
	return result;
}

FrequencyOverlay interpolateCommonFrequencyGrid (const FrequencySeries &target, double targetSampleRate,
		const FrequencySeries &reference, double referenceSampleRate)
{
	Melder_require (target.metricId == reference.metricId && target.unit == reference.unit,
		U"Frequency overlays require the same metric and unit.");
	Melder_require (target.frequencyHz.size() == target.values.size() && reference.frequencyHz.size() == reference.values.size() &&
		target.frequencyHz.size() >= 2 && reference.frequencyHz.size() >= 2,
		U"Each frequency series requires at least two frequency/value pairs.");
	Melder_require (std::isfinite (targetSampleRate) && targetSampleRate > 0.0 &&
		std::isfinite (referenceSampleRate) && referenceSampleRate > 0.0,
		U"Frequency overlay sample rates must be positive.");
	auto validateSeries = [] (const FrequencySeries &series) {
		double previous = - std::numeric_limits<double>::infinity();
		for (size_t index = 0; index < series.frequencyHz.size(); index ++) {
			Melder_require (std::isfinite (series.frequencyHz [index]) && std::isfinite (series.values [index]) &&
				series.frequencyHz [index] > previous,
				U"Frequency points must be finite and strictly increasing, with finite values.");
			previous = series.frequencyHz [index];
		}
	};
	validateSeries (target);
	validateSeries (reference);
	const double minimumFrequency = std::max (target.frequencyHz.front(), reference.frequencyHz.front());
	const double maximumFrequency = std::min ({ target.frequencyHz.back(), reference.frequencyHz.back(),
		targetSampleRate * 0.5, referenceSampleRate * 0.5 });
	Melder_require (minimumFrequency < maximumFrequency,
		U"The two spectra have no common frequency range below both Nyquist limits.");
	const size_t numberOfPoints = std::max<size_t> (2, std::min (target.frequencyHz.size(), reference.frequencyHz.size()));
	FrequencyOverlay result;
	result.metricId = target.metricId;
	result.unit = target.unit;
	result.frequencyHz.reserve (numberOfPoints);
	result.targetValues.reserve (numberOfPoints);
	result.referenceValues.reserve (numberOfPoints);
	for (size_t index = 0; index < numberOfPoints; index ++) {
		const double fraction = (double) index / (double) (numberOfPoints - 1);
		const double frequency = minimumFrequency + fraction * (maximumFrequency - minimumFrequency);
		result.frequencyHz.push_back (frequency);
		result.targetValues.push_back (interpolateAt (target, frequency));
		result.referenceValues.push_back (interpolateAt (reference, frequency));
	}
	result.sampleRatesDiffer = std::abs (targetSampleRate - referenceSampleRate) >= 1.0e-9;
	if (result.sampleRatesDiffer)
		result.warning = U"Different sample rates; both spectra are interpolated only over the common band below the lower Nyquist frequency.";
	return result;
}

double votMilliseconds (double burstTime, double voicingTime) {
	return (voicingTime - burstTime) * 1000.0;
}

AnalysisResult analyseVOT (const SegmentInput &input, std::optional<double> burstTime,
		std::optional<double> voicingTime, VOTBoundaryMode mode, const VOTCandidateSettings &candidateSettings)
{
	if (! input.samples)
		Melder_throw (U"VOT analysis requires a Sound segment.");
	if (burstTime.has_value() != voicingTime.has_value())
		Melder_throw (U"VOT boundaries must either both be supplied or both be omitted.");
	if (mode == VOTBoundaryMode::manual && ! burstTime.has_value())
		Melder_throw (U"Manual VOT analysis requires both burstTime and voicingTime.");
	if (mode == VOTBoundaryMode::estimateCandidates && burstTime.has_value())
		Melder_throw (U"estimateCandidates mode does not accept explicit boundaries.");
	if (! std::isfinite (input.samples -> xmin) || ! std::isfinite (input.samples -> xmax) || input.samples -> xmin >= input.samples -> xmax)
		Melder_throw (U"The Sound has an invalid time domain.");
	if (! std::isfinite (input.metadata.startTime) || ! std::isfinite (input.metadata.endTime) ||
			input.metadata.startTime >= input.metadata.endTime || input.metadata.startTime < input.samples -> xmin ||
			input.metadata.endTime > input.samples -> xmax)
		Melder_throw (U"The VOT analysis range must be increasing and inside the Sound time domain.");
	if (mode == VOTBoundaryMode::estimateCandidates)
		return estimateVOTCandidates (input, candidateSettings);

	if (! std::isfinite (burstTime.value()) || ! std::isfinite (voicingTime.value()))
		Melder_throw (U"VOT boundary times must be finite time values.");
	if (burstTime.value() < input.samples -> xmin || burstTime.value() > input.samples -> xmax)
		Melder_throw (U"burstTime falls outside the Sound time domain.");
	if (voicingTime.value() < input.samples -> xmin || voicingTime.value() > input.samples -> xmax)
		Melder_throw (U"voicingTime falls outside the Sound time domain.");

	const double votInSeconds = voicingTime.value() - burstTime.value();
	const double votInMilliseconds = votMilliseconds (burstTime.value(), voicingTime.value());
	AnalysisResult result;
	result.kind = AnalysisKind::VOT;
	result.source = input.metadata;
	result.source.burstTime = burstTime;
	result.source.voicingTime = voicingTime;
	result.parameters.values.push_back ({ U"boundaryMode", U"manual", U"" });
	result.parameters.compatibilityKeys.push_back (U"boundaryMode");
	result.metrics.push_back ({ U"vot_s", U"s", votInSeconds, MetricStatus::measured, U"" });
	result.metrics.push_back ({ U"vot_ms", U"ms", votInMilliseconds, MetricStatus::measured, U"" });
	return result;
}

AnalysisResult confirmVOTBoundaries (const SegmentInput &input, const AnalysisResult *candidates,
		double burstTime, double voicingTime)
{
	if (candidates)
		Melder_require (candidates -> kind == AnalysisKind::VOT,
			U"Only VOT candidates can be confirmed as VOT boundaries.");
	AnalysisResult result = analyseVOT (input, burstTime, voicingTime, VOTBoundaryMode::manual);
	for (ParameterValue &parameter : result.parameters.values) {
		if (parameter.name == U"boundaryMode")
			parameter.value = U"manualConfirmed";
	}
	if (candidates) {
		for (const ParameterValue &parameter : candidates -> parameters.values) {
			if (parameter.name == U"boundaryMode")
				continue;
			result.parameters.values.push_back ({ U"candidate." + parameter.name, parameter.value, parameter.unit });
		}
		for (const MetricResult &metric : candidates -> metrics) {
			if (metric.id == U"burst_time_candidate" || metric.id == U"burst_rise_db" ||
				metric.id == U"voicing_time_candidate" || metric.id == U"voicing_f0_hz")
				result.metrics.push_back (metric);
		}
	}
	result.metrics.push_back ({ U"burst_time_confirmed", U"s", burstTime, MetricStatus::measured,
		U"Manually confirmed boundary; see burst_time_s in source metadata." });
	result.metrics.push_back ({ U"voicing_time_confirmed", U"s", voicingTime, MetricStatus::measured,
		U"Manually confirmed boundary; see voicing_time_s in source metadata." });
	return result;
}

void AnalysisResult_toTsv (const AnalysisResult &result, MelderString *output) {
	MelderString_empty (output);
	MelderString_append (output,
		U"schema_version\tpraat_version\tsource\tsource_object_id\tsource_file\tsource_start_s\tsource_end_s\tsource_duration_s\tsource_sample_rate_hz\tsource_channels\tsource_kind\tanalysis_kind\tparameters\tlanguage\tipa\tspeaker_id\tneighboring_vowel\tburst_time_s\tvoicing_time_s\tmetric_id\tvalue\tunit\tstatus\treason\n");
	for (const MetricResult &metric : result.metrics) {
		MelderString_append (output, result.schemaVersion, U"\t");
		appendTsvField (output, Melder_appVersionSTR());
		MelderString_appendCharacter (output, U'\t');
		appendTsvSourceMetadata (output, result.source, result.parameters, result.kind);
		MelderString_appendCharacter (output, U'\t');
		appendTsvOptionalNumber (output, result.source.burstTime);
		MelderString_appendCharacter (output, U'\t');
		appendTsvOptionalNumber (output, result.source.voicingTime);
		MelderString_appendCharacter (output, U'\t');
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

void ComparisonResult_toTsv (const ComparisonResult &result, MelderString *output) {
	MelderString_empty (output);
	MelderString_append (output,
		U"schema_version\tpraat_version\tmetric_id\ttarget_source\ttarget_object_id\ttarget_file\ttarget_start_s\ttarget_end_s\ttarget_duration_s\ttarget_sample_rate_hz\ttarget_channels\ttarget_source_kind\ttarget_analysis_kind\ttarget_parameters\ttarget_language\ttarget_ipa\ttarget_speaker_id\ttarget_neighboring_vowel"
		U"\treference_source\treference_object_id\treference_file\treference_start_s\treference_end_s\treference_duration_s\treference_sample_rate_hz\treference_channels\treference_source_kind\treference_analysis_kind\treference_parameters\treference_language\treference_ipa\treference_speaker_id\treference_neighboring_vowel"
		U"\tunit\ttarget_value\treference_value\tdifference\ttarget_status\treference_status\ttarget_reason\treference_reason\treason\twarning\tfrequency_grid_hz\ttarget_frequency_values\treference_frequency_values\tfrequency_warning\tfrequency_reason\n");
	for (const MetricComparison &row : result.rows) {
		MelderString_append (output, result.schemaVersion, U"\t");
		appendTsvField (output, Melder_appVersionSTR());
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, row.metricId);
		MelderString_appendCharacter (output, U'\t');
		appendTsvSourceMetadata (output, result.target, result.targetParameters, result.targetKind);
		MelderString_appendCharacter (output, U'\t');
		appendTsvSourceMetadata (output, result.reference, result.referenceParameters, result.referenceKind);
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, row.unit);
		MelderString_appendCharacter (output, U'\t');
		if (row.targetStatus != MetricStatus::unavailable)
			appendTsvOptionalNumber (output, row.targetValue);
		MelderString_appendCharacter (output, U'\t');
		if (row.referenceStatus != MetricStatus::unavailable)
			appendTsvOptionalNumber (output, row.referenceValue);
		MelderString_appendCharacter (output, U'\t');
		appendTsvOptionalNumber (output, row.difference);
		MelderString_append (output, U"\t", metricStatusName (row.targetStatus), U"\t", metricStatusName (row.referenceStatus), U"\t");
		appendTsvField (output, row.targetReason);
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, row.referenceReason);
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, row.reason);
		MelderString_appendCharacter (output, U'\t');
		appendTsvField (output, row.warning);
		MelderString_appendCharacter (output, U'\t');
		const FrequencyOverlay *overlay = findFrequencyOverlay (result, row.metricId);
		if (overlay) {
			appendTsvNumberVector (output, overlay -> frequencyHz);
			MelderString_appendCharacter (output, U'\t');
			appendTsvNumberVector (output, overlay -> targetValues);
			MelderString_appendCharacter (output, U'\t');
			appendTsvNumberVector (output, overlay -> referenceValues);
			MelderString_appendCharacter (output, U'\t');
			appendTsvField (output, overlay -> warning);
			MelderString_appendCharacter (output, U'\t');
			appendTsvField (output, overlay -> reason);
		} else {
			MelderString_append (output, U"\t\t\t");
		}
		MelderString_appendCharacter (output, U'\n');
	}
}

void writeSegmentAnalysisTsvAtomically (conststring32 resultFileName, conststring32 serialized) {
	Melder_require (resultFileName && resultFileName [0] != U'\0', U"A result file path is required.");
	structMelderFile outputFile {}, temporaryFile {};
	Melder_pathToFile (resultFileName, & outputFile);
	static std::atomic<std::uint64_t> sequence { 0 };
	const integer processId =
	#if defined (_WIN32)
		(integer) _getpid();
	#else
		(integer) getpid();
	#endif
	bool foundUnusedTemporaryPath = false;
	autoMelderString temporaryPath;
	for (int attempt = 0; attempt < 100; attempt ++) {
		MelderString_empty (& temporaryPath);
		MelderString_append (& temporaryPath, resultFileName, U".tmp.", processId, U".",
			(integer) sequence.fetch_add (1, std::memory_order_relaxed));
		Melder_pathToFile (temporaryPath.string, & temporaryFile);
		if (! MelderFile_exists (& temporaryFile)) {
			foundUnusedTemporaryPath = true;
			break;
		}
	}
	Melder_require (foundUnusedTemporaryPath, U"Could not allocate a unique temporary result file.");
	try {
		MelderFile_writeText_e (& temporaryFile, serialized, kMelder_textOutputEncoding::UTF8);
		MelderFile_replaceAtomically (& temporaryFile, & outputFile);
	} catch (MelderError) {
		MelderFile_delete (& temporaryFile);
		throw;
	} catch (const std::exception &) {
		MelderFile_delete (& temporaryFile);
		throw;
	}
}
