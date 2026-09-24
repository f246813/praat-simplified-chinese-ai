#include "SegmentAcousticAnalysis.h"

#include "Sound_and_Spectrum.h"
#include "Sound_to_Harmonicity.h"
#include "Sound_to_Intensity.h"
#include "Sound_to_Pitch.h"

#include <algorithm>

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

	Sound sound = const_cast<Sound> (input.samples);
	const double minimumTime = input.metadata.startTime;
	const double maximumTime = input.metadata.endTime;
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
		const double hnrEnd = std::min (voicingTime.value() + settings.hnrSliceSeconds, input.samples -> xmax);
		if (hnrEnd - voicingTime.value() >= settings.hnrMinimumSliceSeconds) {
			try {
				autoSound hnrSlice = Sound_extractPart (input.samples, voicingTime.value(), hnrEnd,
					kSound_windowShape::RECTANGULAR, 1.0, false);
				autoHarmonicity hnr = Sound_to_Harmonicity_cc (hnrSlice.get(), settings.pitchTimeStepSeconds,
					settings.pitchFloorHz, 0.1, 1.0);
				double maximumHnr = 0.0;
				for (integer frame = 1; frame <= hnr -> nx; frame ++)
					maximumHnr = std::max (maximumHnr, hnr -> z [1] [frame]);
				hnrMaximum = maximumHnr;
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
