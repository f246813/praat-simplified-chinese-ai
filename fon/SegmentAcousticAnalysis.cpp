#include "SegmentAcousticAnalysis.h"

#include "Sound_and_Spectrum.h"
#include "Sound_to_Harmonicity.h"
#include "Sound_to_Intensity.h"
#include "Sound_to_Pitch.h"
#include "melder_app.h"
#include "melder_files.h"
#include "../sys/praat_translate.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <limits>
#include <cmath>

#if defined (_WIN32)
	#include <process.h>
#else
	#include <unistd.h>
#endif

namespace {

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

void appendTsvSourceMetadata (MelderString *output, const SegmentMetadata &metadata,
		const ParameterSnapshot &parameters)
{
	appendTsvField (output, metadata.source.displayName);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalInteger (output, metadata.source.objectId);
	MelderString_appendCharacter (output, U'\t');
	appendTsvOptionalText (output, metadata.source.filePath);
	MelderString_append (output, U"\t", Melder_double (metadata.startTime), U"\t", Melder_double (metadata.endTime), U"\t",
		Melder_double (metadata.endTime - metadata.startTime), U"\t", Melder_double (metadata.source.sampleRate), U"\t",
		metadata.source.channels, U"\t", metadata.source.kind == SourceKind::sound ? U"Sound" : U"LongSound", U"\t",
		U"VOT\t");
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

conststring32 metricStatusName (MetricStatus status) {
	switch (status) {
		case MetricStatus::measured: return U"measured";
		case MetricStatus::warning: return U"warning";
		case MetricStatus::ambiguous: return U"ambiguous";
		case MetricStatus::targetIncomplete: return U"target_incomplete";
		case MetricStatus::unavailable: return U"unavailable";
	}
	return U"unavailable";
}

std::u32string numberAsText (double value) {
	return std::u32string (Melder_double (value));
}

void addParameter (AnalysisResult &result, conststring32 name, double value, conststring32 unit) {
	result.parameters.values.push_back ({ name, numberAsText (value), unit });
}

void addTextParameter (AnalysisResult &result, conststring32 name, conststring32 value, conststring32 unit = U"") {
	result.parameters.values.push_back ({ name, value, unit });
}

void addMetric (AnalysisResult &result, conststring32 id, conststring32 unit,
		std::optional<double> value, MetricStatus status, conststring32 reason)
{
	result.metrics.push_back ({ id, unit, value, status, reason });
}

struct EnvelopeRise {
	double onset { 0.0 };
	double riseDb { 0.0 };
};

struct PitchCandidateOnset {
	double time { 0.0 };
	double frequency { 0.0 };
};

std::optional<PitchCandidateOnset> findPitchCandidateBacktrack (Pitch pitch, integer runStartFrame,
		double referenceFrequency, double minimumTime, double maximumBacktrackSeconds,
		double minimumStrength, double maximumRelativeFrequencyDifference, integer requiredFrames)
{
	if (runStartFrame <= 1 || referenceFrequency <= 0.0 || requiredFrames <= 0)
		return {};
	integer matchedFrames = 0;
	std::optional<PitchCandidateOnset> earliest;
	for (integer frame = runStartFrame - 1; frame >= 1; frame --) {
		const double frameTime = pitch -> x1 + (frame - 1) * pitch -> dx;
		const double runStartTime = pitch -> x1 + (runStartFrame - 1) * pitch -> dx;
		if (frameTime < minimumTime || runStartTime - frameTime > maximumBacktrackSeconds)
			break;
		const Pitch_Frame pitchFrame = & pitch -> frames [frame];
		std::optional<PitchCandidateOnset> match;
		double strongestMatch = minimumStrength;
		for (integer candidateIndex = 1; candidateIndex <= pitchFrame -> nCandidates; candidateIndex ++) {
			const Pitch_Candidate candidate = & pitchFrame -> candidates [candidateIndex];
			if (candidate -> frequency <= 0.0 || candidate -> strength < minimumStrength ||
					std::abs (candidate -> frequency - referenceFrequency) / referenceFrequency > maximumRelativeFrequencyDifference)
				continue;
			if (! match || candidate -> strength > strongestMatch) {
				match = PitchCandidateOnset { frameTime, candidate -> frequency };
				strongestMatch = candidate -> strength;
			}
		}
		if (! match)
			break;
		earliest = match;
		matchedFrames ++;
	}
	return matchedFrames >= requiredFrames ? earliest : std::optional<PitchCandidateOnset> {};
}

std::vector<EnvelopeRise> findEnvelopeRises (constIntensity envelope, double minimumTime, double maximumTime,
		const VOTCandidateSettings &settings)
{
	std::vector<EnvelopeRise> result;
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
		if (laterValue < currentValue - settings.burstRiseHoldDropDb)
			continue;
		double onset = frameTime;
	const double maximumBacktrackSeconds = settings.burstRiseLookbackFrames * envelope -> dx;
		const double referenceValue = currentValue;
		for (integer backFrame = frame - 1; backFrame >= 1; backFrame --) {
			const double backTime = envelope -> x1 + (backFrame - 1) * envelope -> dx;
			if (frameTime - backTime > maximumBacktrackSeconds || backTime < minimumTime ||
					envelope -> z [1] [backFrame] < referenceValue - settings.burstOnsetBacktrackDropDb)
				break;
			onset = backTime;
		}
		if (! result.empty() && onset - result.back().onset < settings.burstCandidateSeparationSeconds) {
			if (rise > result.back().riseDb)
				result.back() = { onset, rise };
		} else {
			result.push_back ({ onset, rise });
		}
	}
	return result;
}

void discardWeakRises (std::vector<EnvelopeRise> &candidates, double minimumRiseDb) {
	candidates.erase (std::remove_if (candidates.begin(), candidates.end(), [&] (const EnvelopeRise &candidate) {
		return candidate.riseDb < minimumRiseDb;
	}), candidates.end());
}

struct BurstDetection {
	std::vector<EnvelopeRise> candidates;
	std::optional<double> time;
	double riseDb { 0.0 };
	std::u32string band;
	std::u32string path;
	std::u32string fallbackReason;
	std::u32string reason;
};

BurstDetection detectBurst (Sound sound, double minimumTime, double maximumTime, const VOTCandidateSettings &settings) {
	BurstDetection result;
	const double nyquistFrequency = 0.5 / sound -> dx;
	if (nyquistFrequency >= settings.burstBandMaximumHz) {
		try {
			autoSound highBandSound = Sound_filter_passHannBand (sound,
				settings.burstBandMinimumHz, settings.burstBandMaximumHz, settings.burstBandSmoothingHz);
			autoIntensity highBandEnvelope = Sound_to_Intensity (
				highBandSound.get(), 2000.0, settings.intensityTimeStepSeconds, true);
			result.candidates = findEnvelopeRises (highBandEnvelope.get(), minimumTime, maximumTime, settings);
			discardWeakRises (result.candidates, settings.burstThresholdDb);
			if (! result.candidates.empty()) {
				const EnvelopeRise &strongest = * std::max_element (result.candidates.begin(), result.candidates.end(),
					[] (const EnvelopeRise &left, const EnvelopeRise &right) { return left.riseDb < right.riseDb; });
				result.time = strongest.onset;
				result.riseDb = strongest.riseDb;
				result.band = U"high-band";
				result.path = U"high-band";
				return result;
			}
			result.fallbackReason = U"High-band analysis found no sustained rise above threshold.";
		} catch (MelderError) {
			Melder_clearError ();
			result.fallbackReason = U"High-band filtering or envelope analysis failed.";
		}
	} else {
		result.fallbackReason = U"Nyquist frequency was below the requested high-band maximum.";
	}
	try {
		autoIntensity broadbandEnvelope = Sound_to_Intensity (sound, 1000.0, settings.intensityTimeStepSeconds, true);
		result.candidates = findEnvelopeRises (broadbandEnvelope.get(), minimumTime, maximumTime, settings);
		discardWeakRises (result.candidates, settings.burstThresholdDb);
		if (! result.candidates.empty()) {
			const EnvelopeRise &strongest = * std::max_element (result.candidates.begin(), result.candidates.end(),
				[] (const EnvelopeRise &left, const EnvelopeRise &right) { return left.riseDb < right.riseDb; });
			result.time = strongest.onset;
			result.riseDb = strongest.riseDb;
			result.band = U"full-band";
			result.path = U"full-band-fallback";
			return result;
		}
	} catch (MelderError) {
		Melder_clearError ();
		result.fallbackReason += U"; full-band envelope analysis failed";
	}
	result.reason = U"No sustained target-region energy rise reached the ";
	result.reason += Melder_double (settings.burstThresholdDb);
	result.reason += U" dB threshold in the high-band or full-band envelope.";
	result.band = U"unavailable";
	result.path = U"unavailable";
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
	if (! std::isfinite (settings.burstCandidateSeparationSeconds) || settings.burstCandidateSeparationSeconds <= 0.0 ||
			! std::isfinite (settings.maximumPositiveVotSeconds) || settings.maximumPositiveVotSeconds <= 0.0 ||
			! std::isfinite (settings.maximumPrevoicingLeadSeconds) || settings.maximumPrevoicingLeadSeconds <= 0.0 ||
			! std::isfinite (settings.minimumHnrDb))
		Melder_throw (U"VOT candidate-pair and HNR validity settings must be finite and positive where applicable.");
}

AnalysisResult estimateVOTCandidates (const SegmentInput &input, const VOTCandidateSettings &settings) {
	validateVOTCandidateSettings (settings);
	if (! std::isfinite (input.metadata.startTime) || ! std::isfinite (input.metadata.endTime) ||
			input.metadata.startTime >= input.metadata.endTime || input.metadata.startTime < input.samples -> xmin ||
			input.metadata.endTime > input.samples -> xmax)
		Melder_throw (U"Candidate estimation requires a valid target selection inside the Sound time domain.");

	VOTDetectionScope scope { input.metadata.startTime, input.metadata.endTime,
		input.metadata.startTime, input.metadata.endTime, {}, {} };
	if (input.votScope)
		scope = input.votScope.value();
	const bool hasAlignedStart = scope.alignedPhoneStartTime.has_value();
	const bool hasAlignedEnd = scope.alignedPhoneEndTime.has_value();
	if (hasAlignedStart != hasAlignedEnd)
		Melder_throw (U"The aligned target phone requires both start and end times.");
	if (! std::isfinite (scope.contextStartTime) || ! std::isfinite (scope.contextEndTime) ||
			scope.contextStartTime >= scope.contextEndTime || scope.contextStartTime < input.samples -> xmin ||
			scope.contextEndTime > input.samples -> xmax || ! std::isfinite (scope.targetStartTime) ||
			! std::isfinite (scope.targetEndTime) || scope.targetStartTime >= scope.targetEndTime ||
			scope.targetStartTime < scope.contextStartTime || scope.targetEndTime > scope.contextEndTime)
		Melder_throw (U"VOT context and target ranges must be increasing and inside the Sound time domain.");
	const double searchStart = hasAlignedStart ? scope.alignedPhoneStartTime.value() : scope.targetStartTime;
	const double searchEnd = hasAlignedEnd ? scope.alignedPhoneEndTime.value() : scope.targetEndTime;
	if (! std::isfinite (searchStart) || ! std::isfinite (searchEnd) || searchStart >= searchEnd ||
			searchStart < scope.contextStartTime || searchEnd > scope.contextEndTime)
		Melder_throw (U"The aligned target phone must be inside the acoustic context.");
	if (hasAlignedStart && (scope.targetStartTime > searchStart || scope.targetEndTime < searchEnd)) {
		AnalysisResult incomplete {};
		incomplete.source = input.metadata;
		addTextParameter (incomplete, U"boundaryMode", U"estimateCandidates");
		addTextParameter (incomplete, U"algorithmVersion", U"context-pair-v4");
		addTextParameter (incomplete, U"candidateStatus", U"target_incomplete");
		const std::u32string reason = U"The target selection clips the aligned phone.";
		for (const auto &metric : { std::pair { U"burst_time_candidate", U"s" }, { U"burst_rise_db", U"dB" },
				{ U"voicing_time_candidate", U"s" }, { U"voicing_f0_hz", U"Hz" }, { U"hnr_max_db", U"dB" },
				{ U"second_voicing_time_candidate", U"s" }, { U"vot_candidate_s", U"s" }, { U"vot_candidate_ms", U"ms" } })
			addMetric (incomplete, metric.first, metric.second, {}, MetricStatus::targetIncomplete, reason.c_str());
		addTextParameter (incomplete, U"candidateFailureReason", reason.c_str());
		return incomplete;
	}

	const double minimumTime = scope.contextStartTime;
	const double maximumTime = scope.contextEndTime;
	auto extractedSegment = Sound_extractPart (const_cast<Sound> (input.samples), minimumTime, maximumTime,
		kSound_windowShape::RECTANGULAR, 1.0, true);
	Sound sound = extractedSegment.get();
	BurstDetection burst = detectBurst (sound, searchStart, searchEnd, settings);
	autoPitch pitch = Sound_to_Pitch_rawAc (sound,
		settings.pitchTimeStepSeconds, settings.pitchFloorHz, settings.pitchCeilingHz,
		settings.maximumPitchCandidates, false, settings.pitchSilenceThreshold, settings.pitchVoicingThreshold,
		settings.pitchOctaveCost, settings.pitchOctaveJumpCost, settings.pitchVoicedUnvoicedCost);

	std::optional<double> voicingTime;
	std::optional<double> secondVoicingTime;
	double voicingOnsetF0 = 0.0;
	double runStart = -1.0;
	double runStartF0 = 0.0;
	double lastVoicedTime = -1.0;
	double secondRunStart = -1.0;
	integer voicedRun = 0;
	integer runStartFrame = 0;

	for (integer frame = 1; frame <= pitch -> nx; frame ++) {
		const double frameTime = pitch -> x1 + (frame - 1) * pitch -> dx;
		if (frameTime < minimumTime || frameTime > maximumTime)
			continue;
		const double frequency = pitch -> frames [frame]. candidates [1]. frequency;
		if (frequency > 0.0) {
			voicedRun ++;
			if (voicedRun == 1) {
				runStart = frameTime;
				runStartF0 = frequency;
				runStartFrame = frame;
			}
			if (! voicingTime && voicedRun >= settings.stableVoicedFrames) {
				const bool runAfterBurst = burst.time && runStart >= burst.time.value() &&
					runStart - burst.time.value() <= settings.maximumPositiveVotSeconds;
				// A pitch frame centred on the release can look voiced before the actual vowel begins.
				const double minimumPrevoicingLead = settings.stableVoicedFrames * settings.pitchTimeStepSeconds;
				const bool runSpansBurst = burst.time && runStart >= searchStart &&
					runStart <= burst.time.value() - minimumPrevoicingLead &&
					burst.time.value() - runStart <= settings.maximumPrevoicingLeadSeconds &&
					frameTime >= burst.time.value();
				if (runAfterBurst || runSpansBurst) {
					voicingTime = runStart;
					voicingOnsetF0 = runStartF0;
					const double earliestAllowedOnset = burst.time ?
						(runStart >= burst.time.value() ? burst.time.value() :
							std::max (minimumTime, burst.time.value() - settings.maximumPrevoicingLeadSeconds)) : minimumTime;
					const double candidateBacktrackSeconds = 1.5 / settings.pitchFloorHz;
					std::optional<PitchCandidateOnset> candidateOnset = findPitchCandidateBacktrack (pitch.get(), runStartFrame,
						runStartF0, earliestAllowedOnset, candidateBacktrackSeconds,
						0.75 * settings.pitchVoicingThreshold, 0.20, settings.stableVoicedFrames);
					if (candidateOnset) {
						voicingTime = candidateOnset -> time;
						voicingOnsetF0 = candidateOnset -> frequency;
					}
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
	if (voicingTime) {
		const bool releaseFollowsPrevoicing = std::any_of (burst.candidates.begin(), burst.candidates.end(),
			[&] (const EnvelopeRise &candidate) {
				return candidate.onset > voicingTime.value() &&
					candidate.onset - voicingTime.value() <= settings.maximumPrevoicingLeadSeconds;
			});
		if (releaseFollowsPrevoicing) {
			burst.candidates.erase (std::remove_if (burst.candidates.begin(), burst.candidates.end(),
				[&] (const EnvelopeRise &candidate) {
					return std::abs (candidate.onset - voicingTime.value()) <= 2.0 * settings.pitchTimeStepSeconds;
				}), burst.candidates.end());
			if (! burst.candidates.empty()) {
				const EnvelopeRise &strongest = * std::max_element (burst.candidates.begin(), burst.candidates.end(),
					[] (const EnvelopeRise &left, const EnvelopeRise &right) { return left.riseDb < right.riseDb; });
				burst.time = strongest.onset;
				burst.riseDb = strongest.riseDb;
			} else {
				burst.time.reset();
			}
		}
	}

	AnalysisResult result;
	result.source = input.metadata;
	addTextParameter (result, U"boundaryMode", U"estimateCandidates");
	addTextParameter (result, U"algorithmVersion", U"context-pair-v4");
	addParameter (result, U"pitchCandidateBacktrackSeconds", 1.5 / settings.pitchFloorHz, U"s");
	addParameter (result, U"pitchCandidateStrengthRatio", 0.75, U"relative");
	addParameter (result, U"pitchCandidateRelativeFrequencyTolerance", 0.20, U"relative");
	addTextParameter (result, U"burstDetectionPath", burst.path.c_str());
	addTextParameter (result, U"burstDetectionBand", burst.band.c_str());
	addTextParameter (result, U"burstDetectionFallbackReason", burst.fallbackReason.c_str());
	addParameter (result, U"targetStartTime", scope.targetStartTime, U"s");
	addParameter (result, U"targetEndTime", scope.targetEndTime, U"s");
	addParameter (result, U"contextStartTime", scope.contextStartTime, U"s");
	addParameter (result, U"contextEndTime", scope.contextEndTime, U"s");
	if (hasAlignedStart) {
		addParameter (result, U"alignedPhoneStartTime", searchStart, U"s");
		addParameter (result, U"alignedPhoneEndTime", searchEnd, U"s");
	}
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
	addParameter (result, U"burstCandidateSeparationSeconds", settings.burstCandidateSeparationSeconds, U"s");
	addParameter (result, U"maximumPositiveVotSeconds", settings.maximumPositiveVotSeconds, U"s");
	addParameter (result, U"maximumPrevoicingLeadSeconds", settings.maximumPrevoicingLeadSeconds, U"s");
	addParameter (result, U"secondVoicingGapSeconds", settings.secondVoicingGapSeconds, U"s");
	addParameter (result, U"hnrSliceSeconds", settings.hnrSliceSeconds, U"s");
	addParameter (result, U"hnrMinimumSliceSeconds", settings.hnrMinimumSliceSeconds, U"s");
	addParameter (result, U"minimumHnrDb", settings.minimumHnrDb, U"dB");
	addParameter (result, U"burstCandidateCount", (double) burst.candidates.size(), U"candidates");

	const bool secondVoicingCanPair = burst.time && secondVoicingTime &&
		secondVoicingTime.value() >= burst.time.value() &&
		secondVoicingTime.value() - burst.time.value() <= settings.maximumPositiveVotSeconds;
	if (burst.candidates.size() > 1 || secondVoicingCanPair) {
		const std::u32string reason = burst.candidates.size() > 1 ?
			U"Multiple target-region release candidates remain plausible; review the pairing manually." :
			U"Multiple stable voiced runs can pair with the target release; review the onset manually.";
		for (const auto &metric : { std::pair { U"burst_time_candidate", U"s" }, { U"burst_rise_db", U"dB" },
				{ U"voicing_time_candidate", U"s" }, { U"voicing_f0_hz", U"Hz" }, { U"hnr_max_db", U"dB" },
				{ U"second_voicing_time_candidate", U"s" }, { U"negative_vot_prevoicing_evidence", U"boolean" },
				{ U"vot_candidate_s", U"s" }, { U"vot_candidate_ms", U"ms" } })
			addMetric (result, metric.first, metric.second, {}, MetricStatus::ambiguous, reason.c_str());
		addTextParameter (result, U"candidateStatus", U"ambiguous");
		addTextParameter (result, U"candidateFailureReason", reason.c_str());
		return result;
	}

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

	if (voicingTime) {
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
	if (voicingTime) {
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

	if (burst.time && voicingTime && hnrMaximum && hnrMaximum.value() >= settings.minimumHnrDb) {
		const double votSeconds = voicingTime.value() - burst.time.value();
		addMetric (result, U"vot_candidate_s", U"s", votSeconds, MetricStatus::warning,
			U"Difference of estimated candidates; confirm both boundaries before reporting VOT.");
		addMetric (result, U"vot_candidate_ms", U"ms", votMilliseconds (burst.time.value(), voicingTime.value()),
			MetricStatus::warning, U"Difference of estimated candidates; confirm both boundaries before reporting VOT.");
		addMetric (result, U"negative_vot_prevoicing_evidence", U"boolean",
			voicingTime.value() < burst.time.value() ? 1.0 : 0.0, MetricStatus::measured,
			voicingTime.value() < burst.time.value() ? U"Stable target-related voicing spans the release." : U"No negative prevoicing was used.");
		addTextParameter (result, U"candidateStatus", U"candidate");
		addTextParameter (result, U"candidateFailureReason", U"");
	} else {
		const std::u32string reason = ! burst.time ? U"Burst candidate unavailable: " + burst.reason :
			voicingTime ? U"Stable voiced onset failed the HNR validity threshold." :
			U"Voicing candidate unavailable for the fixed acoustic context.";
		addMetric (result, U"vot_candidate_s", U"s", {}, MetricStatus::unavailable, reason.c_str());
		addMetric (result, U"vot_candidate_ms", U"ms", {}, MetricStatus::unavailable, reason.c_str());
		addMetric (result, U"negative_vot_prevoicing_evidence", U"boolean", {}, MetricStatus::unavailable, reason.c_str());
		addTextParameter (result, U"candidateStatus", U"failed");
		addTextParameter (result, U"candidateFailureReason", reason.c_str());
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
	result.source = input.metadata;
	result.source.burstTime = burstTime;
	result.source.voicingTime = voicingTime;
	result.parameters.values.push_back ({ U"boundaryMode", U"manual", U"" });
	result.metrics.push_back ({ U"vot_s", U"s", votInSeconds, MetricStatus::measured, U"" });
	result.metrics.push_back ({ U"vot_ms", U"ms", votInMilliseconds, MetricStatus::measured, U"" });
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
		appendTsvSourceMetadata (output, result.source, result.parameters);
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

const MetricResult *AnalysisResult_findMetric (const AnalysisResult &result, conststring32 id) {
	const auto found = std::find_if (result.metrics.begin(), result.metrics.end(), [id] (const MetricResult &metric) {
		return metric.id == id;
	});
	return found == result.metrics.end() ? nullptr : & *found;
}

VOTDisplayData AnalysisResult_toVOTDisplayData (const AnalysisResult &result, VOTBoundaryMode mode) {
	VOTDisplayData display;
	display.mode = mode;
	const auto readMetric = [& result] (conststring32 id) -> std::optional<double> {
		const MetricResult *metric = AnalysisResult_findMetric (result, id);
		if (! metric || metric -> status == MetricStatus::unavailable || ! metric -> value ||
			! std::isfinite (metric -> value.value()))
			return {};
		return metric -> value;
	};
	const MetricResult *votMetric = nullptr;
	if (mode == VOTBoundaryMode::estimateCandidates) {
		display.burstTime = readMetric (U"burst_time_candidate");
		display.voicingTime = readMetric (U"voicing_time_candidate");
		votMetric = AnalysisResult_findMetric (result, U"vot_candidate_ms");
	} else {
		display.burstTime = result.source.burstTime;
		display.voicingTime = result.source.voicingTime;
		votMetric = AnalysisResult_findMetric (result, U"vot_ms");
	}
	if (votMetric && votMetric -> status != MetricStatus::unavailable && votMetric -> value &&
		std::isfinite (votMetric -> value.value()) && display.burstTime && display.voicingTime &&
		std::isfinite (display.burstTime.value()) && std::isfinite (display.voicingTime.value()))
	{
		display.valueMs = votMilliseconds (display.burstTime.value(), display.voicingTime.value());
	} else if (mode == VOTBoundaryMode::estimateCandidates) {
		const auto appendBoundaryFailure = [&display] (const MetricResult *metric, conststring32 fallback) {
			if (! display.failureReason.empty())
				display.failureReason += U"; ";
			if (metric && ! metric -> reason.empty())
				display.failureReason += metric -> reason;
			else
				display.failureReason += fallback;
		};
		if (! display.burstTime)
			appendBoundaryFailure (AnalysisResult_findMetric (result, U"burst_time_candidate"),
				U"Burst/release-time candidate is unavailable.");
		if (! display.voicingTime)
			appendBoundaryFailure (AnalysisResult_findMetric (result, U"voicing_time_candidate"),
				U"Voicing-onset candidate is unavailable.");
		if (display.failureReason.empty() && votMetric && ! votMetric -> reason.empty())
			display.failureReason = votMetric -> reason;
		if (display.failureReason.empty())
			display.failureReason = U"Automatic VOT candidate is unavailable.";
	} else {
		if (votMetric && ! votMetric -> reason.empty())
			display.failureReason = votMetric -> reason;
		else
			display.failureReason = U"Manual VOT value is unavailable.";
	}
	return display;
}

void AnalysisResult_toInfoSummary (const AnalysisResult &result, MelderString *output) {
	MelderString_empty (output);
	if (! result.source.source.displayName.empty())
		MelderString_append (output, U"Source: ", result.source.source.displayName.c_str(), U"\n");
	if (std::isfinite (result.source.startTime) && std::isfinite (result.source.endTime) &&
			result.source.startTime < result.source.endTime)
		MelderString_append (output, U"Range: ", Melder_fixed (result.source.startTime, 3), U"–",
			Melder_fixed (result.source.endTime, 3), U" s\n");

	const auto appendMetric = [&] (conststring32 label, const MetricResult &metric, bool requiresReview,
			conststring32 qualifier) {
		MelderString_append (output, label, U": ");
		if (metric.status == MetricStatus::unavailable || ! metric.value) {
			MelderString_append (output, U"unavailable");
		} else {
			const integer decimals = metric.unit == U"s" ? 3 : 1;
			MelderString_append (output, Melder_fixed (metric.value.value(), decimals));
			if (! metric.unit.empty())
				MelderString_append (output, U" ", metric.unit.c_str());
		}
		if (requiresReview)
			MelderString_append (output, U" (", praat_translate (U"requires manual review"), U")");
		else if (metric.status == MetricStatus::warning)
			MelderString_append (output, U" (warning)");
		if (qualifier)
			MelderString_append (output, U" ", qualifier);
		if (! metric.reason.empty())
			MelderString_append (output, U" — ", metric.reason.c_str());
		MelderString_appendCharacter (output, U'\n');
	};

	if (const MetricResult *manualVot = AnalysisResult_findMetric (result, U"vot_ms")) {
		appendMetric (U"VOT", * manualVot, false, U"(manual measurement)");
		if (result.source.burstTime)
			MelderString_append (output, U"Burst time: ", Melder_fixed (result.source.burstTime.value(), 3), U" s\n");
		if (result.source.voicingTime)
			MelderString_append (output, U"Voicing onset: ", Melder_fixed (result.source.voicingTime.value(), 3), U" s\n");
		return;
	}

	if (const MetricResult *candidateVot = AnalysisResult_findMetric (result, U"vot_candidate_ms"))
		appendMetric (praat_translate (U"Automatically estimated candidate"), * candidateVot, true, nullptr);
	for (const MetricResult &metric : result.metrics) {
		conststring32 label = nullptr;
		if (metric.id == U"burst_time_candidate") label = U"Burst candidate";
		else if (metric.id == U"voicing_time_candidate") label = U"Voicing onset candidate";
		else if (metric.id == U"burst_rise_db") label = U"Burst energy rise";
		else if (metric.id == U"voicing_f0_hz") label = U"Voicing onset frequency";
		else if (metric.id == U"hnr_max_db") label = U"Maximum HNR";
		else if (metric.id == U"second_voicing_time_candidate") label = U"Second voicing candidate";
		if (label)
			appendMetric (label, metric, metric.status == MetricStatus::warning, nullptr);
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
