/* Praat_tests.cpp
 *
 * Copyright (C) 2001-2007,2009,2011-2026 Paul Boersma, David Weenink 2025
 *
 * This code is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3 of the License, or (at
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

/* December 10, 2006: MelderInfo */
/* November 5, 2007: wchar */
/* 21 March 2009: modern enums */
/* 24 May 2011: C++ */
/* 5 June 2015: char32 */

#include "FileInMemory.h"
#include "NUMselect.h"
#include "SlopeSelector.h"
#include "Praat_tests.h"
#include "../sys/PraatAiProjectDirectory.h"

#include "Graphics.h"
#include "praat.h"
#include "NUM2.h"
#include "Sound.h"
#include "SegmentAcousticAnalysis.h"
#include "Harmonicity.h"
#include "Sound_extensions.h"

#include "enums_getText.h"
#include "Praat_tests_enums.h"
#include "enums_getValue.h"
#include "Praat_tests_enums.h"
#include <string>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <random>

#include "Gui.h"

static void testAutoData (autoDaata data) {
	fprintf (stderr, "testAutoData: %p %p\n", data.get(), data -> name.get());
}
static void testAutoDataRef (autoDaata& data) {
	fprintf (stderr, "testAutoDataRef: %p %p\n", data.get(), data -> name.get());
}
static void testData (Daata data) {
	fprintf (stderr, "testData: %p %s\n", data, Melder_peek32to8 (data -> name.get()));
}
static autoDaata newAutoData () {
	autoDaata data (Thing_new (Daata));
	return data;
}

static bool segmentVOTFailsWith (const SegmentInput &input, std::optional<double> burstTime,
		std::optional<double> voicingTime, VOTBoundaryMode mode, conststring32 expectedError)
{
	try {
		(void) analyseVOT (input, burstTime, voicingTime, mode);
	} catch (MelderError) {
		const bool matched = Melder_hasError (expectedError);
		Melder_clearError ();
		return matched;
	}
	return false;
}

static bool segmentVOTNear (double value, double expected) {
	return std::abs (value - expected) < 1e-9;
}

static bool segmentVOTWithin (double value, double expected, double tolerance) {
	return std::abs (value - expected) < tolerance;
}

enum class SegmentVOTFixture {
	positive,
	lowPitch,
	prevoiced,
	transientOnly
};

static autoSound createSegmentVOTFixture (SegmentVOTFixture fixture) {
	constexpr double sampleRate = 44100.0;
	constexpr double duration = 0.6;
	constexpr double samplePeriod = 1.0 / sampleRate;
	constexpr integer numberOfSamples = (integer) (duration * sampleRate);
	autoSound result = Sound_create (1, 0.0, duration, numberOfSamples, samplePeriod, samplePeriod / 2.0);
	const bool prevoiced = fixture == SegmentVOTFixture::prevoiced;
	const bool transientOnly = fixture == SegmentVOTFixture::transientOnly;
	const double voiceOnset = fixture == SegmentVOTFixture::lowPitch ? 0.332 : prevoiced ? 0.28 : 0.33;
	const double fundamental = fixture == SegmentVOTFixture::lowPitch ? 80.0 : 220.0;
	std::mt19937 noiseGenerator (12345);
	std::normal_distribution<double> burstNoise (0.0, 1.0);
	for (integer i = 1; i <= numberOfSamples; i ++) {
		const double time = result -> x1 + (i - 1) * result -> dx;
		const bool voiced = ! transientOnly && time >= voiceOnset;
		const double vocalFoldSignal = voiced ? 0.4 * sin (2.0 * NUMpi * fundamental * time) : 0.0;
		const double burstEnd = transientOnly ? 0.301 : 0.33;
		const bool burst = time >= 0.30 && time < burstEnd;
		const double burstSignal = burst ? (prevoiced ? 0.15 : 0.3) * burstNoise (noiseGenerator) : 0.0;
		result -> z [1] [i] = vocalFoldSignal + burstSignal;
	}
	return result;
}

static const MetricResult *findSegmentVOTMetric (const AnalysisResult &result, conststring32 metricId) {
	for (const MetricResult &metric : result.metrics) {
		if (metric.id == metricId)
			return & metric;
	}
	return nullptr;
}
static integer length (conststring32 s) {
	const integer result = Melder_length (s);
	Melder_free (s);
	return result;
}

static autoMAT constantHH (integer nrow, integer ncol, double value) {
	autoMAT result = raw_MAT (nrow, ncol);
	result.all()  <<=  value;
	return result;
}

int Praat_tests (kPraatTests itest, conststring32 arg1, conststring32 arg2, conststring32 arg3, conststring32 arg4) {
	int64 n = Melder_atoi (arg1);
	double t = 0.0;
	(void) arg1;
	(void) arg2;
	(void) arg3;
	(void) arg4;
	Melder_clearInfo ();
	Melder_stopwatch ();
	switch (itest) {
		case kPraatTests::UNDEFINED:
		case kPraatTests::_:
		case kPraatTests::CHECK_RANDOM_1009_2009: {
		} break;
		case kPraatTests::TIME_RANDOM_FRACTION: {
			for (int64 i = 1; i <= n; i ++)
				(void) NUMrandomFraction ();
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_RANDOM_GAUSS: {
			for (int64 i = 1; i <= n; i ++)
				(void) NUMrandomGauss (0.0, 1.0);
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_SORT: {
			integer size = Melder_atoi (arg2);
			autoVEC array = raw_VEC (size);
			Melder_stopwatch ();
			for (int64 iteration = 1; iteration <= n; iteration ++) {
				for (int64 i = 1; i <= size; i ++)
					array [i] = NUMrandomFraction ();
				sort_e_VEC_inout (array.get());
			}
			t = Melder_stopwatch () / (size * log2 (size));
		} break;
		case kPraatTests::TIME_INTEGER: {
			int64 sum = 0;
			for (int64 i = 1; i <= n; i ++)
				sum += i * (i - 1) * (i - 2);
			t = Melder_stopwatch ();
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_FLOAT: {
			double sum = 0.0, fn = n;
			for (double fi = 1.0; fi <= fn; fi += 1.0)
				sum += fi * (fi - 1.0) * (fi - 2.0);
			t = Melder_stopwatch ();   // 2.02 ns
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_FLOAT_TO_UNSIGNED_BUILTIN: {
			uint64 sum = 0;
			double fn = n;
			for (double fi = 1.0; fi <= fn; fi += 1.0)
				sum += (uint32) fi;
			t = Melder_stopwatch ();   // 1.45 ns
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_FLOAT_TO_UNSIGNED_EXTERN: {
			uint64 sum = 0;
			double fn = n;
			for (double fi = 1.0; fi <= fn; fi += 1.0)
				sum += (uint32) ((int32) (fi - 2147483648.0) + 2147483647L + 1);
			t = Melder_stopwatch ();   // 1.47 ns
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_UNSIGNED_TO_FLOAT_BUILTIN: {
			double sum = 0.0;
			uint32 nu = (uint32) n;
			for (uint32 iu = 1; iu <= nu; iu ++)
				sum += (double) iu;
			t = Melder_stopwatch ();   // 0.88 ns
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_UNSIGNED_TO_FLOAT_EXTERN: {
			double sum = 0.0;
			uint32 nu = (uint32) n;
			for (uint32 iu = 1; iu <= nu; iu ++)
				sum += (double) (int32) (iu - 2147483647L - 1) + 2147483648.0;
			t = Melder_stopwatch ();   // 0.87 ns
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_STRING_MELDER_32: {
			autoMelderString string;
			char32 word [] { U"abc" };
			word [2] = char32 (NUMrandomInteger (U'a', U'z'));
			for (int64 i = 1; i <= n; i ++) {
				MelderString_copy (& string, word);
				for (int j = 1; j <= 30; j ++)
					MelderString_append (& string, word);
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_MELDER_32_ALLOC: {
			char32 word [] { U"abc" };
			word [2] = char32 (NUMrandomInteger (U'a', U'z'));
			for (int64 i = 1; i <= n; i ++) {
				autoMelderString string;
				MelderString_copy (& string, word);
				for (int j = 1; j <= 30; j ++)
					MelderString_append (& string, word);
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_S: {
			std::string s = "";
			char word [] { "abc" };
			word [2] = char (NUMrandomInteger ('a', 'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_C: {
			std::basic_string<char> s = "";
			char word [] { "abc" };
			word [2] = char (NUMrandomInteger ('a', 'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_WS: {
			std::wstring s = L"";
			wchar_t word [] { L"abc" };
			word [2] = wchar_t (NUMrandomInteger (L'a', L'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_WC: {
			std::basic_string<wchar_t> s = L"";
			wchar_t word [] { L"abc" };
			word [2] = wchar_t (NUMrandomInteger (L'a', L'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_32: {
			std::basic_string<char32_t> s = U"";
			char32 word [] { U"abc" };
			word [2] = char32 (NUMrandomInteger (U'a', U'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRING_CPP_U32STRING: {
			std::u32string s = U"";
			char32 word [] { U"abc" };
			word [2] = char32 (NUMrandomInteger (U'a', U'z'));
			for (int64 i = 1; i <= n; i ++) {
				s = word;
				for (int j = 1; j <= 30; j ++)
					s += word;
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STRCPY: {
			char buffer [100];
			char word [] { "abc" };
			word [2] = (char) NUMrandomInteger ('a', 'z');
			for (int64 i = 1; i <= n; i ++) {
				strcpy (buffer, word);
				for (int j = 1; j <= 30; j ++)
					strcpy (buffer + strlen (buffer), word);
			}
			t = Melder_stopwatch ();
			MelderInfo_writeLine (Melder_peek8to32_u (buffer));
		} break;
		case kPraatTests::TIME_WCSCPY: {
			wchar_t buffer [100];
			wchar_t word [] { L"abc" };
			word [2] = wchar_t (NUMrandomInteger (L'a', L'z'));
			for (int64 i = 1; i <= n; i ++) {
				wcscpy (buffer, word);
				for (int j = 1; j <= 30; j ++)
					wcscpy (buffer + wcslen (buffer), word);
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_STR32CPY: {
			char32 buffer [100];
			char32 word [] { U"abc" };
			word [2] = char32 (NUMrandomInteger (U'a', U'z'));
			for (int64 i = 1; i <= n; i ++) {
				str32cpy (buffer, word);
				for (int j = 1; j <= 30; j ++)
					str32cpy (buffer + Melder_length (buffer), word);
			}
			t = Melder_stopwatch ();
			MelderInfo_writeLine (buffer);
		} break;
		case kPraatTests::TIME_GRAPHICS_TEXT_TOP: {
			autoPraatPictureOpen picture;
			for (int64 i = 1; i <= n; i ++) {
				Graphics_textTop (GRAPHICS, false, U"hello world");
			}
			t = Melder_stopwatch ();
		} break;
		case kPraatTests::TIME_UNDEFINED_NUMUNDEFINED: {
			bool isAllDefined = true;
			double x = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				x += (double) i;
				isAllDefined &= ( x != undefined );
			}
			t = Melder_stopwatch ();   // 0.86 ns
			MelderInfo_writeLine (isAllDefined, U" ", x);
		} break;
		case kPraatTests::TIME_UNDEFINED_ISINF_OR_ISNAN: {
			bool isAllDefined = true;
			double x = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				x += (double) i;
				isAllDefined &= ! isinf (x) && ! isnan (x);
				//isAllDefined &= ! isfinite (x);   // same
			}
			t = Melder_stopwatch ();   // 1.29 ns
			MelderInfo_writeLine (isAllDefined, U" ", x);
		} break;
		case kPraatTests::TIME_UNDEFINED_0x7FF: {
			bool isAllDefined = true;
			double x = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				x += (double) i;
				isAllDefined &= ((* (uint64 *) & x) & 0x7FF0'0000'0000'0000) != 0x7FF0'0000'0000'0000;
			}
			t = Melder_stopwatch ();   // 0.90 ns
			MelderInfo_writeLine (isAllDefined, U" ", x);
		} break;
		case kPraatTests::TIME_INNER: {
			integer size = Melder_atoi (arg2);
			autoVEC x = randomGauss_VEC (size, 0.0, 1.0);
			autoVEC y = randomGauss_VEC (size, 0.0, 1.0);
			double z = 0.0;
			for (int64 i = 1; i <= n; i ++)
				z += NUMinner (x.get(), y.get());
			t = Melder_stopwatch () / size;   // 2.9 Gops = 5.8 Gflops (multiplication-addition pair)
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_OUTER_NUMMAT: {
			integer nrow = 100, ncol = 100;
			autoVEC x = randomGauss_VEC (nrow, 0.0, 1.0);
			autoVEC y = randomGauss_VEC (ncol, 0.0, 1.0);
			for (int64 i = 1; i <= n; i ++)
				const autoMAT mat = outer_MAT (x.get(), y.get());
			t = Melder_stopwatch () / nrow / ncol;   // 6.1 Gops, i.e. less than one clock cycle per cell
		} break;
		case kPraatTests::CHECK_INVFISHERQ: {
			MelderInfo_writeLine (NUMinvFisherQ (0.003, 1, 100000));
		} break;
		case kPraatTests::TIME_AUTOSTRING: {
			conststring32 strings [6] = { U"ghdg", U"jhd", U"hkfjjd", U"fhfj", U"jhksfd", U"hfjs" };
			int64 sumOfLengths = 0;
			for (int64 i = 1; i <= n; i ++) {
				int istring = i % 6;
				autostring32 s = Melder_dup (strings [istring]);
				sumOfLengths += length (s.transfer());
			}
			t = Melder_stopwatch ();   // 72 ns (but 152 bytes more)
			MelderInfo_writeLine (sumOfLengths);
		} break;
		case kPraatTests::TIME_CHAR32: {
			conststring32 strings [6] = { U"ghdg", U"jhd", U"hkfjjd", U"fhfj", U"jhksfd", U"hfjs" };
			int64 sumOfLengths = 0;
			for (int64 i = 1; i <= n; i ++) {
				int istring = i % 6;
				char32 *s = Melder_dup (strings [istring]).transfer();
				sumOfLengths += length (s);
			}
			t = Melder_stopwatch ();   // 72 ns
			MelderInfo_writeLine (sumOfLengths);
		} break;
		case kPraatTests::TIME_SUM: {
			integer size = Melder_atoi (arg2);
			autoVEC x = randomGauss_VEC (size, 0.0, 1.0);
			double z = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				double sum = NUMsum (x.get());
				z += sum;
			}
			t = Melder_stopwatch () / size;   // for size == 100: 0.31 ns
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_MEAN: {
			integer size = Melder_atoi (arg2);
			autoVEC x = randomGauss_VEC (size, 0.0, 1.0);
			double z = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				double sum = NUMmean (x.get());
				z += sum;
			}
			t = Melder_stopwatch () / size;   // for size == 100: 0.34 ns
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_STDEV: {
			integer size = 10000;
			autoVEC x = randomGauss_VEC (size, 0.0, 1.0);
			double z = 0.0;
			for (int64 i = 1; i <= n; i ++) {
				double stdev = NUMstdev (x.get());
				z += stdev;
			}
			t = Melder_stopwatch () / size;
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_ALLOC: {
			integer size = Melder_atoi (arg2);
			for (int64 iteration = 1; iteration <= n; iteration ++) {
				autoVEC result = raw_VEC (size);
				for (integer i = 1; i <= size; i ++)
					result [i] = 0.0;
			}
			t = Melder_stopwatch () / size;   // 10^0..7: 70/6.9/1.08 / 0.074/0.0074/0.0091 / 0.51/0.00026 ns
		} break;
		case kPraatTests::TIME_ALLOC0: {
			integer size = Melder_atoi (arg2);
			for (int64 iteration = 1; iteration <= n; iteration ++)
				autoVEC result = zero_VEC (size);
			t = Melder_stopwatch () / size;   // 10^0..7: 76/7.7/1.23 / 0.165/0.24/0.25 / 1.30/1.63 ns
		} break;
		case kPraatTests::TIME_ZERO: {
			integer size = Melder_atoi (arg2);
			autoVEC result = raw_VEC (size);
			double z = 0.0;
			for (int64 iteration = 1; iteration <= n; iteration ++) {
				for (integer i = 1; i <= size; i ++)
					result [i] = (double) i;
				z += result [size - 1];
			}
			t = Melder_stopwatch () / size;
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_MALLOC: {
			integer size = Melder_atoi (arg2);
			double value = Melder_atof (arg3);
			double z = 0.0;
			for (int64 iteration = 1; iteration <= n; iteration ++) {
				double *result = (double *) malloc (sizeof (double) * (size_t) size);
				for (integer i = 0; i < size; i ++)
					result [i] = value;
				z += result [size / 2];
				free (result);
			}
			t = Melder_stopwatch () / size;
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_CALLOC: {
			integer size = Melder_atoi (arg2);
			double z = 0.0;
			for (integer iteration = 1; iteration <= n; iteration ++) {
				double *result = (double *) calloc (sizeof (double), (size_t) size);
				z += result [size / 2];
				free (result);
			}
			t = Melder_stopwatch () / size;
			MelderInfo_writeLine (z);
		} break;
		case kPraatTests::TIME_ADD: {
			integer size = Melder_atoi (arg2);
			autoMAT result = randomGauss_MAT (size, size, 0.0, 1.0);
			Melder_stopwatch ();
			for (integer iteration = 1; iteration <= n; iteration ++)
				result.all()  <<=  5.0;
			t = Melder_stopwatch () / size / size;   // 10^0..4: 2.7/0.16/0.24 / 0.38/0.98
			double sum = NUMsum (result.get());
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_SIN: {
			integer size = Melder_atoi (arg2);
			autoMAT result = randomGauss_MAT (size, size, 0.0, 1.0);
			Melder_stopwatch ();
			for (integer iteration = 1; iteration <= n; iteration ++)
				sin_MAT_inout (result.get());
			t = Melder_stopwatch () / size / size;   // 10^0..4: 18/5.3/5.2 / 5.3/12
			double sum = NUMsum (result.get());
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_VECADD: {
			integer size = Melder_atoi (arg2);
			autoVEC x = randomGauss_VEC (size, 0.0, 1.0);
			autoVEC y = randomGauss_VEC (size, 0.0, 1.0);
			autoVEC result = raw_VEC (size);
			Melder_stopwatch ();
			for (integer iteration = 1; iteration <= n; iteration ++)
				//add_VEC_out (result.all(), x.all(), y.all());
				result.all()  <<=  x.all() + y.all();
			t = Melder_stopwatch () / size;
			double sum = NUMsum (result.get());
			MelderInfo_writeLine (sum);
		} break;
		case kPraatTests::TIME_MATMUL: {
			const integer size1 = Melder_atoi (arg2);
			integer size2 = Melder_atoi (arg3);
			integer size3 = Melder_atoi (arg4);
			if (size2 == 0 || size3 == 0) size3 = size2 = size1;
			//autoMAT const x = randomGauss_MAT (size1, size2, 0.0, 1.0);
			//autoMAT const y = randomGauss_MAT (size2, size3, 0.0, 1.0);
			autoMAT x = constantHH (size1, size2, 10.0);
			autoMAT y = constantHH (size2, size3, 3.0);
			autoMAT const result = raw_MAT (size1, size3);
			//MAT resultget = result.get();
			//constMAT xget = x.get(), yget = y.get();
			MATVU const result_all = result.all();
			constMATVU const x_all = x.all();
			constMATVU const y_all = y.all();
			Melder_stopwatch ();
			for (integer iteration = 1; iteration <= n; iteration ++)
				//MATmul_forceMetal_ (result_all, x_all, y_all);
				_mul_allowAllocation_MAT_out (result_all, x_all, y_all);
			const integer numberOfComputations = size1 * size2 * size3 * 2;
			t = Melder_stopwatch () / numberOfComputations;
			const double sum = NUMsum (result.get());
			const integer numberOfStores = size1 * size2 + size2 * size3 + size1 * size3 + 10000;
			MelderInfo_writeLine (double (numberOfComputations) / double (numberOfStores), U" computations per store");
			MelderInfo_writeLine (sum, U" should be ", size1 * size2 * size3 * 30.0);
			//Melder_require (NUMequal (result.get(), constantHH (size, size, size * 30.0).get()), U"...");
		} break;
		case kPraatTests::THING_AUTO: {
			integer numberOfThingsBefore = theTotalNumberOfThings;
			{
				Melder_casual (U"1\n");
				autoDaata data = Thing_new (Daata);
				Thing_setName (data.get(), U"hello");
				Melder_casual (U"2\n");
				testData (data.get());
				testAutoData (data.move());
				autoDaata data18 = Thing_new (Daata);
				testAutoData (data18.move());
				fprintf (stderr, "3\n");
				autoDaata data2 = newAutoData ();
				fprintf (stderr, "4\n");
				autoDaata data3 = newAutoData ();
				fprintf (stderr, "5\n");
				//data2 = data;   // disabled l-value copy assignment from same class
				fprintf (stderr, "6\n");
				autoOrdered ordered = Thing_new (Ordered);
				fprintf (stderr, "7\n");
				//data = ordered;   // disabled l-value copy assignment from subclass
				data = ordered.move();
				//ordered = data;   // disabled l-value copy assignment from superclass
				//ordered = data.move();   // assignment from superclass to subclass is rightfully refused by compiler
				fprintf (stderr, "8\n");
				data2 = newAutoData ();
				fprintf (stderr, "8a\n");
				autoDaata data5 = newAutoData ();
				fprintf (stderr, "8b\n");
				data2 = data5.move();
				fprintf (stderr, "9\n");
				//ordered = data;   // rightfully refused by compiler
				fprintf (stderr, "10\n");
				//autoOrdered ordered2 = Thing_new (Daata);   // rightfully refused by compiler
				fprintf (stderr, "11\n");
				autoDaata data4 = Thing_new (Ordered);   // constructor
				fprintf (stderr, "12\n");
				//autoDaata data6 = data4;   // disabled l-value copy constructor from same class
				fprintf (stderr, "13\n");
				autoDaata data7 = data4.move();
				fprintf (stderr, "14\n");
				autoOrdered ordered3 = Thing_new (Ordered);
				autoDaata data8 = ordered3.move();
				fprintf (stderr, "15\n");
				//autoDaata data9 = ordered;   // disabled l-value copy constructor from subclass
				fprintf (stderr, "16\n");
				autoDaata data10 = data7.move();
				fprintf (stderr, "17\n");
				autoDaata data11 = Thing_new (Daata);   // constructor, move assignment, null destructor
				fprintf (stderr, "18\n");
				data11 = Thing_new (Ordered);
				fprintf (stderr, "19\n");
				testAutoDataRef (data11);
				fprintf (stderr, "20\n");
				//data11 = nullptr;   // disabled implicit assignment of pointer to autopointer
				fprintf (stderr, "21\n");
			}
			integer numberOfThingsAfter = theTotalNumberOfThings;
			fprintf (stderr, "Number of things: before %td, after %td\n", numberOfThingsBefore, numberOfThingsAfter);
			#if 0
				MelderCallback<void,structDaata>::FunctionType f;
				typedef void (*DataFunc) (Daata);
				typedef void (*OrderedFunc) (Ordered);
				DataFunc dataFun;
				OrderedFunc orderedFun;
				MelderCallback<void,structDaata> dataFun2 (dataFun);
				MelderCallback<void,structOrdered> orderedFun2 (orderedFun);
				MelderCallback<void,structDaata> dataFun3 (orderedFun);
				//MelderCallback<void,structOrdered> orderedFun3 (dataFun);   // rightfully refused by compiler
				autoDaata data = Thing_new (Daata);
				dataFun3 (data.get());
			#endif
			{
				#if 1
				autoMelderAsynchronous x;
				//autoMelderAsynchronous y = x;   // deleted copy constructor
				autoMelderAsynchronous y = x.move();   // defined move constructor
				//x = y;   // deleted copy assignment
				x = y.move();   // defined move assignment
				autoVEC a;
				autoVEC b = a.move();
				const autoVEC c;
				const autoVEC d { };
				#if 0
				double *e;
				const autoVEC f { e, 10 };
				#endif
				{
					autoVEC g = zero_VEC (100);
					g [1] = 3.0;
					VEC gg = g.get();
					gg [2] = 4.0;
					constVEC ggg = g.get();
					//ggg [3] = 5.0;   // should be refused by the compiler
					const VEC gggg = g.get();
					//gggg [3] = 6.0;   // should be refused by the compiler
					//return f;   // call to deleted constructor
					//gggg. reset();   // should be refused by the compiler
					//ggg. reset();   // should be refused by the compiler
					//gg. reset();
				}
				{
					double x [3], *px = & x [0];
					const double *cpx = px;
					VEC vx (px, 2);
					constVEC cvx (px, 2);
					const VEC c_vx (px, 2);
					double a = c_vx [1];
					const double b = c_vx [2];
					const double y = 0.0, *py = & y;
					//VEC vy (py, 0);   // ruled out: "No matching constructor for initialization of VEC" (2021-04-03)
					constVEC cvy { py, 2 };
					//const VEC c_vy = VEC (py, 2);   // ruled out: "No matching constructor for initialization of VEC" (2021-04-03)
					const VEC c_vy = (const VEC) VEC (const_cast<double *> (py), 2);
					double c = c_vy [1];
					const double d = c_vy [2];
					//VEC c_vy2 = VEC (py, 2);   // ruled out: "No matching constructor for initialization of VEC" (2021-04-03)
				}
				{
					structSampled sampled {};
					structFunction function {};
					structFunction *pFunction = & sampled;
					structSampled *pSampled = & sampled;
					//structFunction **ppFunction = MelderPointerToPointerCast<structSampled> (& pFunction);   // not allowed
					structFunction **ppSampled = MelderPointerToPointerCast<structFunction> (& pSampled);   // allowed
				}
				{
					const structSampled sampled {};
					const structFunction function {};
					const structFunction *const pFunction = & sampled;
					const structSampled *const pSampled = & sampled;
					const structFunction *const *const ppFunction = & pFunction;
					//const structFunction *const *const ppSampled = & pSampled;   // forbidden
				}

				VEC h;
				autoVEC j;
				//VEC jh = j;   // ruled out: "No viable conversion from autoVEC to VEC" (2021-04-03)
				//VEC zero = zero_VEC (10);   // ruled out: "No viable conversion from autoVEC to VEC" (2021-04-03)
				//constVEC zero = zero_VEC (10);   // ruled out: "No viable conversion from autoVEC to constVEC" (2021-04-03)
				//j = h;   // ruled out: "No viable overloaded '='" (2021-04-03)
				//h = j;   // ruled out: "No viable overloaded '='" (2021-04-03)
				//h = VEC (j);   // ruled out: "No matching conversion for functional-style cast from autoVEC to VEC" (2021-04-03)
				//VEC & jref = j;   // ruled out: "Non-const lvalue reference to type VEC cannot bind to a value of unrelated type autoVEC" (2021-04-03)
				VEC *ph = & h;
				autoVEC *pj = & j;
				//ph = pj;   // correctly ruled out: Assigning to 'VEC' from incompatible type 'autoVEC' (2021-04-03)
				//pj = ph;   // correctly ruled out: "Assigning to 'autoVEC *' from incompatible type 'VEC *' (2021-04-03)
				#endif
				autoSound sound = Sound_create (1, 0.0, 1.0, 10000, 0.0001, 0.0);
				sound = Sound_create (1, 0.0, 1.0, 10000, 0.0001, 0.00005);
				Melder_casual (U"hello ", sound -> dx);
				autoSTRVEC v;
				mutablestring32 *pm = v.peek2();
				const mutablestring32 *pcm = v.peek2();
				//conststring32 *pc = v.peek2();
				const conststring32 *pcc = v.peek2();
				{
					vector<double> aa, bb;
					vector<const double> aac, bbc;
					//aa = aac;
					aa = bb;
					aac = bbc;
					//aac = aa;
					bbc.cells = bb.cells;
				}
			}
		} break;
		case kPraatTests::FILEINMEMORY_IO: {
			//Melder_throw (U"Cannot test FileInMemoryManager directly from Praat.");
			test_FileInMemory_io ();
		} break;
		case kPraatTests::TIME_MEDIAN: {
			timeMedian ();
			//  Gflops is --undefined--
		} break;
		case kPraatTests::TIME_SLOPE_SELECTION: {
			timeSlopeSelection ();
			//  Gflops is --undefined--
		} break;
		case kPraatTests::TIME_NS_DATE: {
			#ifdef macintosh
				NSDate *till = [NSDate   dateWithTimeIntervalSinceNow: 1.0];
				integer count = 0;
				while ([[NSDate date]   compare: till] == NSOrderedAscending)
					++ count;
				MelderInfo_writeLine (count, U" per second");
			#endif
		} break;
		case kPraatTests::TIME_MELDER_CLOCK: {
			const double till = Melder_clock() + 1.0;
			integer count = 0;
			while (Melder_clock() < till)
				++ count;
			MelderInfo_writeLine (count, U" per second");
		} break;
		case kPraatTests::TIME_STOPWATCH: {
			MelderStopwatch stopwatch;
			for (int64 i = 1; i <= n; i ++)
				Melder_stopwatch();
			t = stopwatch ();
		} break;
		case kPraatTests::CHECK_SEGMENT_ANALYSIS_RESULT: {
			AnalysisResult target {};
			target.schemaVersion = 1;
			target.source.source.objectId = 42;
			target.source.source.displayName = U"synthetic";
			target.source.source.filePath = U"D:/recordings/synthetic.wav";
			target.source.source.sampleRate = 16000.0;
			target.source.source.channels = 1;
			target.source.startTime = 0.25;
			target.source.endTime = 0.75;
			target.source.burstTime = 0.0;
			target.source.voicingTime = 0.0;
			target.source.annotation.language = U"zh";
			target.parameters.values.push_back ({ U"boundaryMode", U"manualConfirmed", U"" });
			target.parameters.values.push_back ({ U"burstThresholdDb", U"6", U"dB" });
			target.metrics.push_back ({ U"duration", U"ms", 0.0, MetricStatus::measured, U"" });
			target.metrics.push_back ({ U"A1-P0", U"dB", {}, MetricStatus::unavailable, U"no P0 peak" });
			Melder_assert (target.metrics [0].value.has_value() && target.metrics [0].value.value() == 0.0);
			Melder_assert (! target.metrics [1].value.has_value());
			autoMelderString tsv;
			AnalysisResult_toTsv (target, & tsv);
			Melder_assert (str32str (tsv.string, U"schema_version\tpraat_version\tsource\tsource_object_id\tsource_file\tsource_start_s\tsource_end_s\tsource_duration_s\tsource_sample_rate_hz\tsource_channels\tsource_kind\tanalysis_kind\tparameters\tlanguage\tipa\tspeaker_id\tneighboring_vowel\tburst_time_s\tvoicing_time_s\tmetric_id\tvalue\tunit\tstatus\treason") != nullptr);
			Melder_assert (str32str (tsv.string, U"synthetic\t42\tD:/recordings/synthetic.wav\t0.25\t0.75\t0.5\t16000\t1\tSound\tVOT\tboundaryMode=manualConfirmed; burstThresholdDb=6 dB\tzh") != nullptr);
			Melder_assert (str32str (tsv.string, U"\t0\t0\tduration\t0\tms\tmeasured") != nullptr);
			Melder_assert (str32str (tsv.string, U"\t0\t0\tA1-P0\t\tdB\tunavailable\tno P0 peak") != nullptr);
		} break;
		case kPraatTests::CHECK_SEGMENT_VOT_BOUNDARIES: {
			autoSound samples = Sound_create (1, -0.5, 0.5, 1000, 0.001, -0.4995);
			SegmentInput input;
			input.samples = samples.get ();
			input.metadata.startTime = -0.5;
			input.metadata.endTime = 0.5;
			Melder_assert (segmentVOTNear (votMilliseconds (0.30, 0.32), 20.0));
			Melder_assert (votMilliseconds (0.30, 0.30) == 0.0);
			Melder_assert (segmentVOTNear (votMilliseconds (0.30, 0.28), -20.0));

			const AnalysisResult positive = analyseVOT (input, 0.30, 0.32, VOTBoundaryMode::manual);
			Melder_assert (segmentVOTNear (positive.metrics [0].value.value (), 0.02));
			Melder_assert (segmentVOTNear (positive.metrics [1].value.value (), 20.0));
			Melder_assert (positive.source.burstTime.value () == 0.30);
			Melder_assert (positive.source.voicingTime.value () == 0.32);

			const AnalysisResult zero = analyseVOT (input, 0.0, 0.0, VOTBoundaryMode::manual);
			Melder_assert (zero.metrics [1].value.has_value () && zero.metrics [1].value.value () == 0.0);
			const AnalysisResult prevoiced = analyseVOT (input, -0.30, -0.32, VOTBoundaryMode::manual);
			Melder_assert (segmentVOTNear (prevoiced.metrics [1].value.value (), -20.0));

			Melder_assert (segmentVOTFailsWith (input, {}, {}, VOTBoundaryMode::manual, U"requires both burstTime and voicingTime"));
			Melder_assert (segmentVOTFailsWith (input, 0.30, {}, VOTBoundaryMode::manual, U"both be supplied"));
			Melder_assert (segmentVOTFailsWith (input, 0.60, 0.70, VOTBoundaryMode::manual, U"outside the Sound time domain"));
			Melder_assert (segmentVOTFailsWith (input, std::numeric_limits<double>::quiet_NaN (), 0.32,
				VOTBoundaryMode::manual, U"finite time values"));
			SegmentInput invalidRange = input;
			invalidRange.metadata.startTime = 0.4;
			invalidRange.metadata.endTime = 0.3;
			Melder_assert (segmentVOTFailsWith (invalidRange, 0.30, 0.32, VOTBoundaryMode::manual,
				U"range must be increasing"));
		} break;
		case kPraatTests::CHECK_SEGMENT_VOT_ESTIMATOR: {
			const auto runFixture = [] (SegmentVOTFixture fixture) {
				autoSound samples = createSegmentVOTFixture (fixture);
				SegmentInput input;
				input.samples = samples.get ();
				input.metadata.startTime = 0.25;
				input.metadata.endTime = 0.55;
				input.metadata.source.sampleRate = 1.0 / samples -> dx;
				input.metadata.source.channels = samples -> ny;
				return analyseVOT (input, {}, {}, VOTBoundaryMode::estimateCandidates);
			};
			const AnalysisResult positive = runFixture (SegmentVOTFixture::positive);
			const MetricResult *burst = findSegmentVOTMetric (positive, U"burst_time_candidate");
			const MetricResult *burstRise = findSegmentVOTMetric (positive, U"burst_rise_db");
			const MetricResult *voicing = findSegmentVOTMetric (positive, U"voicing_time_candidate");
			const MetricResult *voicingF0 = findSegmentVOTMetric (positive, U"voicing_f0_hz");
			const MetricResult *hnr = findSegmentVOTMetric (positive, U"hnr_max_db");
			const MetricResult *vot = findSegmentVOTMetric (positive, U"vot_candidate_ms");
			Melder_assert (burst && burst -> value && segmentVOTWithin (burst -> value.value (), 0.30, 0.005));
			Melder_assert (burstRise && burstRise -> value && burstRise -> value.value () >= 6.0 && burstRise -> status == MetricStatus::measured);
			Melder_assert (voicing && voicing -> value && segmentVOTWithin (voicing -> value.value (), 0.33, 0.005));
			Melder_assert (voicingF0 && voicingF0 -> value && voicingF0 -> status == MetricStatus::measured);
			Melder_assert (hnr && hnr -> value && hnr -> status == MetricStatus::measured);
			Melder_assert (vot && vot -> value && segmentVOTWithin (vot -> value.value (), 30.0, 5.0));
			Melder_assert (burst -> status == MetricStatus::warning && voicing -> status == MetricStatus::warning);

			const AnalysisResult lowPitch = runFixture (SegmentVOTFixture::lowPitch);
			const MetricResult *lowPitchVot = findSegmentVOTMetric (lowPitch, U"vot_candidate_ms");
			const MetricResult *lowPitchBurst = findSegmentVOTMetric (lowPitch, U"burst_time_candidate");
			const MetricResult *lowPitchVoice = findSegmentVOTMetric (lowPitch, U"voicing_time_candidate");
			const MetricResult *lowPitchF0 = findSegmentVOTMetric (lowPitch, U"voicing_f0_hz");
			Melder_assert (lowPitchVot && lowPitchVot -> value && lowPitchVot -> status == MetricStatus::warning);
			Melder_assert (segmentVOTWithin (lowPitchVot -> value.value (), 39.0, 5.0));
			Melder_assert (lowPitchBurst && lowPitchBurst -> value && lowPitchVoice && lowPitchVoice -> value);
			Melder_assert (lowPitchVoice -> value.value () > lowPitchBurst -> value.value ());
			Melder_assert (lowPitchF0 && lowPitchF0 -> value && lowPitchF0 -> value.value () >= 60.0 && lowPitchF0 -> value.value () <= 110.0);
			Melder_assert (segmentVOTNear (lowPitchVot -> value.value (),
				votMilliseconds (lowPitchBurst -> value.value (), lowPitchVoice -> value.value ())));

			const AnalysisResult prevoiced = runFixture (SegmentVOTFixture::prevoiced);
			const MetricResult *prevoicedVot = findSegmentVOTMetric (prevoiced, U"vot_candidate_ms");
			Melder_assert (prevoicedVot && prevoicedVot -> value && segmentVOTWithin (prevoicedVot -> value.value (), -20.0, 6.0));
			Melder_assert (prevoicedVot -> status == MetricStatus::warning);

			const AnalysisResult transient = runFixture (SegmentVOTFixture::transientOnly);
			const MetricResult *transientVot = findSegmentVOTMetric (transient, U"vot_candidate_ms");
			Melder_assert (transientVot && ! transientVot -> value && transientVot -> status == MetricStatus::unavailable);

			autoSound boundedSource = createSegmentVOTFixture (SegmentVOTFixture::positive);
			SegmentInput boundedInput;
			boundedInput.samples = boundedSource.get ();
			boundedInput.metadata.startTime = 0.25;
			boundedInput.metadata.endTime = 0.55;
			boundedInput.metadata.source.sampleRate = 1.0 / boundedSource -> dx;
			const AnalysisResult fullSourceRange = analyseVOT (boundedInput, {}, {}, VOTBoundaryMode::estimateCandidates);
			autoSound extractedSource = Sound_extractPart (boundedSource.get(), 0.25, 0.55,
				kSound_windowShape::RECTANGULAR, 1.0, true);
			SegmentInput extractedInput = boundedInput;
			extractedInput.samples = extractedSource.get();
			const AnalysisResult extractedRange = analyseVOT (extractedInput, {}, {}, VOTBoundaryMode::estimateCandidates);
			const MetricResult *fullBurst = findSegmentVOTMetric (fullSourceRange, U"burst_time_candidate");
			const MetricResult *partBurst = findSegmentVOTMetric (extractedRange, U"burst_time_candidate");
			const MetricResult *fullVoice = findSegmentVOTMetric (fullSourceRange, U"voicing_time_candidate");
			const MetricResult *partVoice = findSegmentVOTMetric (extractedRange, U"voicing_time_candidate");
			Melder_assert (fullBurst && partBurst && fullBurst -> value && partBurst -> value);
			Melder_assert (segmentVOTWithin (fullBurst -> value.value(), partBurst -> value.value(), 0.002));
			Melder_assert (fullVoice && partVoice && fullVoice -> value && partVoice -> value);
			Melder_assert (segmentVOTWithin (fullVoice -> value.value(), partVoice -> value.value(), 0.002));
			boundedInput.metadata.endTime = 0.35;
			const AnalysisResult shortRange = analyseVOT (boundedInput, {}, {}, VOTBoundaryMode::estimateCandidates);
			const MetricResult *shortHnr = findSegmentVOTMetric (shortRange, U"hnr_max_db");
			Melder_assert (shortHnr && ! shortHnr -> value && shortHnr -> status == MetricStatus::unavailable);
			autoHarmonicity hnrValues = Harmonicity_create (0.0, 0.03, 3, 0.01, 0.005);
			hnrValues -> z [1] [1] = -12.0;
			hnrValues -> z [1] [2] = -4.0;
			hnrValues -> z [1] [3] = std::numeric_limits<double>::quiet_NaN();
			const std::optional<double> negativeHnrMaximum = maximumDefinedHnr (hnrValues.get());
			Melder_assert (negativeHnrMaximum && negativeHnrMaximum.value() == -4.0);
			for (integer frame = 1; frame <= hnrValues -> nx; frame ++)
				hnrValues -> z [1] [frame] = std::numeric_limits<double>::quiet_NaN();
			Melder_assert (! maximumDefinedHnr (hnrValues.get()));
		} break;
		case kPraatTests::CHECK_SEGMENT_VOT_INFO_SUMMARY: {
			AnalysisResult manual {};
			manual.parameters.values.push_back ({ U"boundaryMode", U"manualConfirmed", U"" });
			manual.metrics.push_back ({ U"vot_ms", U"ms", 0.0, MetricStatus::measured, U"" });
			autoMelderString manualSummary;
			AnalysisResult_toInfoSummary (manual, & manualSummary);
			Melder_assert (str32str (manualSummary.string, U"VOT: 0 ms (manual measurement)") != nullptr);

			AnalysisResult candidate {};
			candidate.parameters.values.push_back ({ U"boundaryMode", U"automaticCandidate", U"" });
			candidate.metrics.push_back ({ U"vot_candidate_ms", U"ms", 20.0, MetricStatus::warning, U"" });
			autoMelderString candidateSummary;
			AnalysisResult_toInfoSummary (candidate, & candidateSummary);
			Melder_assert (str32str (candidateSummary.string, U"requires manual review") != nullptr);
		} break;
		case kPraatTests::CHECK_AI_PROJECT_DIRECTORY_RESOLUTION: {
			const std::filesystem::path temporaryRoot = std::filesystem::temp_directory_path () /
				("praat-ai-project-path-" + std::to_string (
					std::chrono::steady_clock::now ().time_since_epoch ().count ()
				));
			std::error_code filesystemError;
			if (! std::filesystem::create_directory (temporaryRoot, filesystemError) || filesystemError)
				Melder_throw (U"Could not create a unique AI project path test directory.");
			try {
				const std::filesystem::path staleProject = temporaryRoot / "ai";
				const std::filesystem::path realProject = temporaryRoot / "checkout" / "ai";
				std::filesystem::create_directories (staleProject / "runtime");
				std::filesystem::create_directories (realProject);
				std::ofstream (staleProject / "runtime" / "status.json") << "{}";
				std::ofstream (realProject / "run_ai_control.py") << "# AI control entry point";
				std::ofstream (realProject / "start_ai_chat.py") << "# AI chat launcher";
				Melder_assert (! PraatAiProjectDirectory::isProjectDirectory (staleProject));
				Melder_assert (PraatAiProjectDirectory::isProjectDirectory (realProject));
				const auto resolved = PraatAiProjectDirectory::resolve (
					std::filesystem::path ("ai"), temporaryRoot, temporaryRoot
				);
				Melder_assert (resolved.has_value ());
				Melder_assert (resolved.value () == realProject.lexically_normal ());
				const auto resolvedFromStaleAbsolute = PraatAiProjectDirectory::resolve (
					staleProject, temporaryRoot, temporaryRoot
				);
				Melder_assert (resolvedFromStaleAbsolute.has_value ());
				Melder_assert (resolvedFromStaleAbsolute.value () == realProject.lexically_normal ());
			} catch (...) {
				std::filesystem::remove_all (temporaryRoot, filesystemError);
				throw;
			}
			std::filesystem::remove_all (temporaryRoot, filesystemError);
		} break;
	}
	MelderInfo_writeLine (Melder_single (t * 1e9 / n), U" nanoseconds per iteration");
	MelderInfo_close ();
	return 1;
}

/* More compiler stuff */
#if 1
/*
	Trying out inheritance without encapsulation...
	Advantage: everything is a method; therefore, the Law of Demeter is satisfied idiomatically
	Disadvantage: problematic encapsulation
*/
Thing_declare (Matrix_);
Thing_declare (Sound_);
Thing_declare (Pitch_);

/*
	The following two sets of files have to be included
	in Pitch_to_Sound.cpp as well as in Sound_to_Pitch.cpp,
	but can come in either order:
*/

/*
	Set 1: Pitch.h
*/
struct structPitch_ : structThing {
	double f0;
	autoSound_ toSound ();   // anti-encapsulation
};

/*
	Set 2: Matrix.h followed by Sound.h
*/
struct structMatrix_ : structThing {
	private: double x, y;
	public: double getX () { return x; }
	void setX (double newX) { x = newX; }
};
struct structSound_ : public structMatrix_ {   // the definition of structSound_ requires the prior definition of structMatrix_
	autoPitch_ toPitch ();   // anti-encapsulation
};

/*
	The following two files are independent of each other:
*/

/*
	Pitch_to_Sound.cpp:
	#include "Pitch.h"
	#include "Sound.h"
*/
autoSound_ structPitch_::toSound () {   // this requires the prior definition of structPitch_ and the prior declaration of structSound_
	autoSound_ result = autoSound_ ();
	result -> setX (f0);   // this requires the prior definition of structSound_ and structMatrix_
	return result;
}

/*
	Sound_to_Pitch.cpp:
	#include "Sound.h"
	#include "Pitch.h"
*/
autoPitch_ structSound_::toPitch () {   // this requires the prior definition of structSound_ and the prior declaration of structPitch_
	double x = getX ();   // this requires the prior definition of structSound_ and structMatrix_
	autoPitch_ result = autoPitch_ ();
	result -> f0 = x;   // this requires the prior definition of structPitch_
	return result;
}

#endif

/*
	An attempt to not have VEC and constVEC, but VEC and const VEC instead.
*/

class Vec {
public:
	double *at;
	integer size;
	const double *const_propagate_at () const { return at; }
	double *const_propagate_at () { return at; }
public:
	Vec (double *initialAt, integer initialSize) : at (initialAt), size (initialSize) { }
	double& operator[] (integer index) { return at [index]; }   // selected for Vec (1)
	const double& operator[] (integer index) const { return at [index]; }   // selected for const Vec (2)
	//Vec (Vec& other) : at (other.const_propagate_at()), size (other.size) { };   // can assign Vec to Vec (3)
	//Vec (Vec&& other) : at (other.at), size (other.size) { };   // can assign Vec to Vec (3)
	Vec (Vec& other) : at (other.at), size (other.size) { };   // can assign Vec to Vec (3)
	Vec (const Vec& other) = delete;   // cannot assign const Vec to Vec (4)
		/* unfortunately, this also precludes initializing a *const* Vec from a const Vec */
	//Vec (const Vec& other) const = default;   // attempt to copy a const Vec to a const Vec, but constructors cannot be const
	//const Vec (const Vec& other) = default;   // attempt to copy a const Vec to a const Vec, but constructors cannot have a return type
};

/*static void tryVec () {
	Vec x = Vec (nullptr, 0);
	x [1] = 3.0;
	double a = x [2];
	const Vec cx = Vec (nullptr, 0);
	//cx [1] = 3.0;   // should be refused by compiler, because operator[] returns a const value that cannot be assigned to (2)
	a = cx [2];   // should be allowed by compiler, because not an assignment (2)
	const Vec cy = x;   // should be allowed (3)
	//Vec y = cx;   // should be refused (4)
	const Vec cz = copy (x);
	//cx.at [1] = 3.0;
	////const Vec ca = cy;   // should be allowed
}*/

/* End of file Praat_tests.cpp */
