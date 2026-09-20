/* PraatAiControl.cpp
 *
 * Local AI frontend integration for Praat.
 */

#include "PraatAiControl.h"
#include "GuiP.h"
#include "machine.h"
#include "praat.h"
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
	constexpr conststring32 defaultFrontendModel = U"Qwen3.5-0.8B-Q4_K_M.gguf";

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

	bool isProjectDirectory (const std::filesystem::path &directory) {
		std::error_code error;
		return std::filesystem::exists (directory / "run_ai_control.py", error) ||
			std::filesystem::exists (directory / "runtime" / "status.json", error);
	}

	std::filesystem::path projectDirectoryPath () {
		const char32 *directory = theAiProjectDirectory [0] ? theAiProjectDirectory : U"ai";
		autostring8 directory8 = Melder_32to8 (directory);
		const std::filesystem::path configuredDirectory = std::filesystem::u8path (directory8 ? directory8.get() : "ai");
		if (configuredDirectory.is_absolute())
			return configuredDirectory;
		std::error_code error;
		const std::filesystem::path currentDirectory =
			std::filesystem::current_path (error) / configuredDirectory;
		if (isProjectDirectory (currentDirectory))
			return currentDirectory;
		#if defined (_WIN32)
			wchar_t executablePath [MAX_PATH];
			const DWORD executablePathLength = GetModuleFileNameW (
				nullptr, executablePath, static_cast <DWORD> (MAX_PATH)
			);
			if (executablePathLength > 0 && executablePathLength < MAX_PATH) {
				const std::filesystem::path executableDirectory =
					std::filesystem::path (executablePath, executablePath + executablePathLength). parent_path();
				const std::filesystem::path executableRelativeDirectory =
					executableDirectory / configuredDirectory;
				if (isProjectDirectory (executableRelativeDirectory))
					return executableRelativeDirectory;
			}
		#endif
		return currentDirectory;
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

	void setEnvironmentUtf8 (const char *name, const std::string &value) {
		#if defined (_WIN32)
			const int nameLength = MultiByteToWideChar (CP_UTF8, 0, name, -1, nullptr, 0);
			const int valueLength = MultiByteToWideChar (
				CP_UTF8, 0, value. c_str(), static_cast <int> (value. size()), nullptr, 0
			);
			if (nameLength <= 0 || valueLength < 0)
				return;
			std::wstring wideName (nameLength, L'\0');
			std::wstring wideValue (valueLength, L'\0');
			MultiByteToWideChar (CP_UTF8, 0, name, -1, wideName. data(), nameLength);
			if (valueLength > 0)
				MultiByteToWideChar (
					CP_UTF8, 0, value. c_str(), static_cast <int> (value. size()),
					wideValue. data(), valueLength
				);
			SetEnvironmentVariableW (wideName. c_str(), wideValue. c_str());
		#else
			setenv (name, value. c_str(), 1);
		#endif
	}

	void clearEnvironmentUtf8 (const char *name) {
		#if defined (_WIN32)
			const int nameLength = MultiByteToWideChar (CP_UTF8, 0, name, -1, nullptr, 0);
			if (nameLength <= 0)
				return;
			std::wstring wideName (nameLength, L'\0');
			MultiByteToWideChar (CP_UTF8, 0, name, -1, wideName. data(), nameLength);
			SetEnvironmentVariableW (wideName. c_str(), nullptr);
		#else
			unsetenv (name);
		#endif
	}

	void runControlCommand (conststring32 command, conststring32 value = nullptr) {
		const std::string script8 = controlScriptPath(). u8string();
		const std::string directory8 = projectDirectoryPath(). u8string();
		autostring32 script32 = Melder_8to32_e (script8. c_str());
		autostring32 directory32 = Melder_8to32_e (directory8. c_str());
		autostring8 command8 = Melder_32to8 (command ? command : U"");
		autostring8 value8 = Melder_32to8 (value ? value : U"");
		setEnvironmentUtf8 (
			"PRAAT_AI_CONTROL_COMMAND",
			command8 ? command8. get() : ""
		);
		if (value8 && value8. get() [0])
			setEnvironmentUtf8 ("PRAAT_AI_CONTROL_VALUE", value8. get());
		else
			clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_VALUE");
		setEnvironmentUtf8 ("PRAAT_AI_CONTROL_QUIET", "1");
		try {
			praat_runPythonScriptFile (
				script32 ? script32. get() : U"",
				directory32 ? directory32. get() : nullptr
			);
		} catch (...) {
			clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_COMMAND");
			clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_VALUE");
			clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_QUIET");
			throw;
		}
		clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_COMMAND");
		clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_VALUE");
		clearEnvironmentUtf8 ("PRAAT_AI_CONTROL_QUIET");
		PraatAiControl_refreshStatus();
	}

	void setModelPath (conststring32 path) {
		PraatAiControl_refreshStatus();
		runControlCommand (U"set-model", path);
		PraatAiControl_refreshStatus();
	}

	std::string cleanContextField (conststring32 value) {
		autostring8 value8 = Melder_32to8 (value ? value : U"");
		std::string result = value8 ? value8. get() : "";
		std::replace (result. begin(), result. end(), '\t', ' ');
		std::replace (result. begin(), result. end(), '\r', ' ');
		std::replace (result. begin(), result. end(), '\n', ' ');
		return result;
	}

	std::string buildChatContext () {
		std::ostringstream text;
		text << "id\tclass\tname\tselected\n";
		if (theCurrentPraatObjects) {
			for (integer iobject = 1; iobject <= theCurrentPraatObjects -> n; iobject ++) {
				Daata object = theCurrentPraatObjects -> list [iobject]. object;
				if (! object)
					continue;
				text
					<< theCurrentPraatObjects -> list [iobject]. id << '\t'
					<< cleanContextField (Thing_className (object)) << '\t'
					<< cleanContextField (theCurrentPraatObjects -> list [iobject]. name. get()) << '\t'
					<< (theCurrentPraatObjects -> list [iobject]. isSelected ? "1" : "0")
					<< '\n';
			}
		}
		return text. str();
	}

	void writeChatContext (bool force = false) {
		static std::string previousContext;
		const std::string context = buildChatContext ();
		if (! force && context == previousContext)
			return;   // 选中对象没有变化时不重复写盘
		previousContext = context;
		const std::filesystem::path runtimeDirectory = projectDirectoryPath() / "runtime";
		std::error_code error;
		std::filesystem::create_directories (runtimeDirectory, error);
		std::ofstream output (runtimeDirectory / "chat_context.tsv", std::ios::binary | std::ios::trunc);
		if (! output. is_open())
			return;
		output << context;
	}

	std::filesystem::path praatExecutablePath () {
		#if defined (_WIN32)
			wchar_t executablePath [MAX_PATH];
			const DWORD length = GetModuleFileNameW (
				nullptr, executablePath, static_cast <DWORD> (MAX_PATH)
			);
			if (length > 0 && length < MAX_PATH)
				return std::filesystem::path (executablePath, executablePath + length);
		#endif
		return { };
	}

	void launchAiChatWindow () {
		writeChatContext (true);
		const std::filesystem::path launcher = projectDirectoryPath() / "start_ai_chat.py";
		const std::string launcher8 = launcher. u8string();
		const std::string directory8 = projectDirectoryPath(). u8string();
		autostring32 launcher32 = Melder_8to32_e (launcher8. c_str());
		autostring32 directory32 = Melder_8to32_e (directory8. c_str());
		const std::filesystem::path executable = praatExecutablePath ();
		#if defined (_WIN32)
			SetEnvironmentVariableW (
				L"PRAAT_AI_PRAAT_EXECUTABLE",
				executable. empty() ? nullptr : executable. wstring(). c_str()
			);
		#endif
		try {
			praat_runPythonScriptFile (
				launcher32 ? launcher32. get() : U"",
				directory32 ? directory32. get() : nullptr
			);
		} catch (...) {
			#if defined (_WIN32)
				SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_EXECUTABLE", nullptr);
			#endif
			throw;
		}
		#if defined (_WIN32)
			SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_EXECUTABLE", nullptr);
		#endif
	}

}

void PraatAiControl_initPreferences () {
	Preferences_addString (U"AI.projectDirectory", theAiProjectDirectory, U"ai");
	Preferences_addString (U"AI.alignmentMode", theAiAlignmentMode, U"auto");
	MelderString_copy (& statusFrontendModel, defaultFrontendModel);
	MelderString_copy (& statusFrontendStatus, U"stopped");
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
	return statusFrontendModel. string ? statusFrontendModel. string : defaultFrontendModel;
}

conststring32 PraatAiControl_getFrontendStatus () {
	return statusFrontendStatus. string ? statusFrontendStatus. string : U"stopped";
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

void PraatAiControl_chooseFrontendModel () {
	autoStringSet files = GuiFileSelect_getInfileNames (
		nullptr,
		U"Select a GGUF model file",
		false
	);
	if (files -> size > 0)
		setModelPath (files -> at [1] -> string. get());
}

void PraatAiControl_startFrontend () {
	runControlCommand (U"start");
	PraatAiControl_refreshStatus();
	if (statusRunning)
		launchAiChatWindow ();
}

void PraatAiControl_stopFrontend () {
	runControlCommand (U"stop");
	PraatAiControl_refreshStatus();
}

void PraatAiControl_runAnalysis () {
	if (! theCurrentPraatObjects || theCurrentPraatObjects -> totalSelection < 2)
		Melder_throw (U"AI 纠音需要至少两个已选中的 Sound 对象。");
	const std::string script8 = (projectDirectoryPath() / "run_ai_tutor.py"). u8string();
	const std::string directory8 = projectDirectoryPath(). u8string();
	autostring32 script32 = Melder_8to32_e (script8. c_str());
	autostring32 directory32 = Melder_8to32_e (directory8. c_str());
	praat_runPythonScriptFile (
		script32 ? script32. get() : U"",
		directory32 ? directory32. get() : nullptr
	);
}

void PraatAiControl_refreshChatContext () {
	if (Melder_batch)
		return;   // 批处理里没有对话窗口
	writeChatContext ();   // 内容没变化时不会重复写盘
}

/* End of file PraatAiControl.cpp */
