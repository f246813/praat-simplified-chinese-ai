/* PraatAiControl.cpp
 *
 * Local AI frontend integration for Praat.
 */

#include "PraatAiControl.h"
#include "GuiP.h"
#include "machine.h"
#include "melder_sysenv.h"
#include "praat_python.h"
#include "praat_translate.h"
#include "Preferences.h"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>

#if defined (_WIN32)
	#include <windows.h>
#else
	#include <cstdlib>
#endif

namespace {
	char32 theAiProjectDirectory [Preferences_STRING_BUFFER_SIZE];
	char32 theAiAlignmentMode [32];
	bool statusSuccess = false;
	bool statusRunning = false;
	bool statusVramLow = false;
	double statusVramFreeGb = 0.0;
	MelderString statusFrontendModel;
	MelderString statusFrontendStatus;
	char32 theAiProjectDirectoryBuffer [Preferences_STRING_BUFFER_SIZE];

	std::string jsonStringField (const std::string &json, const std::string &name, const std::string &fallback = "") {
		const std::string key = "\"" + name + "\"";
		const size_t keyPosition = json. find (key);
		if (keyPosition == std::string::npos)
			return fallback;
		const size_t colon = json. find (':', keyPosition + key. size());
		if (colon == std::string::npos)
			return fallback;
		const size_t quote1 = json. find ('"', colon + 1);
		if (quote1 == std::string::npos)
			return fallback;
		const size_t quote2 = json. find ('"', quote1 + 1);
		if (quote2 == std::string::npos)
			return fallback;
		return json. substr (quote1 + 1, quote2 - quote1 - 1);
	}

	bool jsonBoolField (const std::string &json, const std::string &name, bool fallback) {
		const std::string key = "\"" + name + "\"";
		const size_t keyPosition = json. find (key);
		if (keyPosition == std::string::npos)
			return fallback;
		const size_t colon = json. find (':', keyPosition + key. size());
		if (colon == std::string::npos)
			return fallback;
		const size_t valueStart = json. find_first_not_of (" \t\r\n", colon + 1);
		if (valueStart == std::string::npos)
			return fallback;
		return json. compare (valueStart, 4, "true") == 0;
	}

	double jsonNumberField (const std::string &json, const std::string &name, double fallback) {
		const std::string key = "\"" + name + "\"";
		const size_t keyPosition = json. find (key);
		if (keyPosition == std::string::npos)
			return fallback;
		const size_t colon = json. find (':', keyPosition + key. size());
		if (colon == std::string::npos)
			return fallback;
		const size_t valueStart = json. find_first_not_of (" \t\r\n", colon + 1);
		if (valueStart == std::string::npos)
			return fallback;
		try {
			return std::stod (json. substr (valueStart));
		} catch (...) {
			return fallback;
		}
	}

	std::filesystem::path projectDirectoryPath () {
		const char32 *directory = theAiProjectDirectory [0] ? theAiProjectDirectory : U"ai";
		autostring8 directory8 = Melder_32to8 (directory);
		return std::filesystem::u8path (directory8 ? directory8.get() : "ai");
	}

	std::filesystem::path controlScriptPath () {
		return projectDirectoryPath() / "run_ai_control.py";
	}

	std::filesystem::path statusPath () {
		return projectDirectoryPath() / "runtime" / "status.json";
	}

	std::optional<std::string> readTextFile (const std::filesystem::path &path) {
		std::ifstream input (path, std::ios::binary);
		if (! input. is_open())
			return std::nullopt;
		return std::string (
			(std::istreambuf_iterator<char> (input)),
			std::istreambuf_iterator<char> ()
		);
	}

	autostring32 runControlCommand (conststring32 command, conststring32 value = nullptr) {
		const std::string script8 = controlScriptPath(). u8string();
		autostring32 script32 = Melder_8to32_e (script8. c_str());
		autoMelderString buffer;
		MelderString_append (
			& buffer,
			U"\"", praat_python_getExecutablePath(), U"\" \"",
			script32 ? script32. get() : U"", U"\" ", command
		);
		if (value && value [0])
			MelderString_append (& buffer, U" \"", value, U"\"");
		return runSystem_STR (buffer. string);
	}

	void setProcessEnvironment (const wchar_t *name, const wchar_t *value) {
		#if defined (_WIN32)
			SetEnvironmentVariableW (name, value);
		#else
			(void) name;
			(void) value;
		#endif
	}

	void clearProcessEnvironment (const wchar_t *name) {
		#if defined (_WIN32)
			SetEnvironmentVariableW (name, nullptr);
		#else
			(void) name;
		#endif
	}

	void setModelPath (conststring32 path) {
		PraatAiControl_refreshStatus();
		runControlCommand (U"set-model", path);
		PraatAiControl_refreshStatus();
	}

	std::unordered_map<GuiMenuItem, int> theModelMenuActions;
	GuiMenuItem theModelPresetItems [2] { };

	void modelMenuCallback (Thing /* boss */, GuiMenuItemEvent event) {
		try {
			const auto iterator = theModelMenuActions. find (event -> menuItem);
			if (iterator == theModelMenuActions. end())
				return;
			switch (iterator -> second) {
				case 1: setModelPath (U"D:/models/Qwen3.5-0.8B-Q4_K_M.gguf"); break;
				case 2: setModelPath (U"D:/llama.cpp/Qwen3.5-2B-UD-Q5_K_XL.gguf"); break;
				case 3: {
					autoStringSet files = GuiFileSelect_getInfileNames (
						nullptr,
						U"Select a GGUF model file",
						false
					);
					if (files -> size > 0)
						setModelPath (files -> at [1] -> string. get());
				} break;
				case 4: PraatAiControl_startFrontend(); break;
				case 5: PraatAiControl_stopFrontend(); break;
				default: break;
			}
			if (theModelPresetItems [0])
				GuiMenuItem_check (theModelPresetItems [0], iterator -> second == 1);
			if (theModelPresetItems [1])
				GuiMenuItem_check (theModelPresetItems [1], iterator -> second == 2);
		} catch (MelderError) {
			Melder_flushError ();
		}
	}
}

void PraatAiControl_initPreferences () {
	Preferences_addString (U"AI.projectDirectory", theAiProjectDirectory, U"ai");
	Preferences_addString (U"AI.alignmentMode", theAiAlignmentMode, U"auto");
	conststring32 configuredDirectory = Melder_getenv (U"PRAAT_AI_PROJECT_DIR");
	if (configuredDirectory && configuredDirectory [0])
		str32cpy (theAiProjectDirectory, configuredDirectory);
}

conststring32 PraatAiControl_getAlignmentMode () {
	return theAiAlignmentMode [0] ? theAiAlignmentMode : U"auto";
}

void PraatAiControl_setAlignmentMode (conststring32 mode) {
	str32cpy (theAiAlignmentMode, mode && mode [0] ? mode : U"auto");
	runControlCommand (U"set-alignment-mode", theAiAlignmentMode);
	PraatAiControl_refreshStatus();
}

bool PraatAiControl_refreshStatus () {
	const auto text = readTextFile (statusPath());
	if (! text)
		return false;
	statusSuccess = jsonBoolField (* text, "success", false);
	statusRunning = jsonBoolField (* text, "frontend_running", false);
	statusVramLow = jsonBoolField (* text, "vram_low", false);
	statusVramFreeGb = jsonNumberField (* text, "vram_free_gb", 0.0);
	const std::string model = jsonStringField (* text, "frontend_model");
	const std::string status = jsonStringField (* text, "frontend_status", "stopped");
	autostring32 model32 = Melder_8to32_e (model. c_str());
	autostring32 status32 = Melder_8to32_e (status. c_str());
	MelderString_copy (& statusFrontendModel, model32 ? model32. get() : U"");
	MelderString_copy (& statusFrontendStatus, status32 ? status32. get() : U"unknown");
	return statusSuccess;
}

conststring32 PraatAiControl_getFrontendModel () {
	return statusFrontendModel. string;
}

conststring32 PraatAiControl_getFrontendStatus () {
	return statusFrontendStatus. string;
}

conststring32 PraatAiControl_getVramText (bool *low) {
	static MelderString text;
	autoMelderString line;
	MelderString_append (& line, praat_translate (U"VRAM: "));
	if (statusVramFreeGb > 0.0)
		MelderString_append (& line, Melder_fixed (statusVramFreeGb, 2), U" G");
	else
		MelderString_append (& line, praat_translate (U"unavailable"));
	MelderString_copy (& text, line. string);
	if (low)
		*low = statusVramLow;
	return text. string;
}

void PraatAiControl_startFrontend () {
	runControlCommand (U"start");
	PraatAiControl_refreshStatus();
}

void PraatAiControl_stopFrontend () {
	runControlCommand (U"stop");
	PraatAiControl_refreshStatus();
}

void PraatAiControl_runAnalysis () {
	#if defined (_WIN32)
		const std::wstring commandName = L"PRAAT_AI_CONTROL_COMMAND";
		const std::wstring commandValue = L"run";
		setProcessEnvironment (commandName. c_str(), commandValue. c_str());
	#else
		setenv ("PRAAT_AI_CONTROL_COMMAND", "run", 1);
	#endif
	try {
		const std::string script8 = controlScriptPath(). u8string();
		const std::string directory8 = projectDirectoryPath(). u8string();
		autostring32 script32 = Melder_8to32_e (script8. c_str());
		autostring32 directory32 = Melder_8to32_e (directory8. c_str());
		praat_runPythonScriptFile (
			script32 ? script32. get() : U"",
			directory32 ? directory32. get() : nullptr
		);
	} catch (...) {
		#if defined (_WIN32)
			clearProcessEnvironment (commandName. c_str());
		#else
			unsetenv ("PRAAT_AI_CONTROL_COMMAND");
		#endif
		throw;
	}
	#if defined (_WIN32)
		clearProcessEnvironment (commandName. c_str());
	#else
		unsetenv ("PRAAT_AI_CONTROL_COMMAND");
	#endif
}

void PraatAiControl_addModelMenu (GuiWindow window) {
	#if motif
		GuiMenu menu = GuiMenu_createInForm (
			window,
			-190, -8,
			Machine_getMenuBarBottom(),
			Machine_getMenuBarBottom() + 24,
			U"Models",
			0
		);
		theModelPresetItems [0] = GuiMenu_addItem (
			menu, U"Qwen3.5-0.8B", GuiMenu_RADIO_FIRST,
			modelMenuCallback, nullptr
		);
		theModelMenuActions [theModelPresetItems [0]] = 1;
		theModelPresetItems [1] = GuiMenu_addItem (
			menu, U"Qwen3.5-2B", GuiMenu_RADIO_NEXT,
			modelMenuCallback, nullptr
		);
		theModelMenuActions [theModelPresetItems [1]] = 2;
		GuiMenu_addSeparator (menu);
		GuiMenuItem customItem = GuiMenu_addItem (
			menu, U"Add model path...", 0, modelMenuCallback, nullptr
		);
		theModelMenuActions [customItem] = 3;
		GuiMenu_addSeparator (menu);
		GuiMenuItem startItem = GuiMenu_addItem (
			menu, U"Start frontend", 0, modelMenuCallback, nullptr
		);
		theModelMenuActions [startItem] = 4;
		GuiMenuItem stopItem = GuiMenu_addItem (
			menu, U"Stop frontend", 0, modelMenuCallback, nullptr
		);
		theModelMenuActions [stopItem] = 5;
	#endif
}

/* End of file PraatAiControl.cpp */
