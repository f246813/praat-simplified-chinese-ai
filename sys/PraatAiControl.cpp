/* PraatAiControl.cpp
 *
 * Local AI frontend integration for Praat.
 */

#include "PraatAiControl.h"
#include "GuiP.h"
#include "praat.h"
#include "praat_python.h"
#include "praat_translate.h"
#include "Preferences.h"
#include "LongSound.h"
#include "SegmentAcousticVOT.h"
#include "Sound.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <optional>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#if defined (_WIN32)
	#include <windows.h>
#else
	#include <cstdlib>
	#include <unistd.h>
#endif

namespace {
	char32 theAiProjectDirectory [Preferences_STRING_BUFFER_SIZE];
	char32 theAiAlignmentMode [32];
	bool statusSuccess = false;
	bool statusRunning = false;
	/*
		API 模式（前端接云端大模型）：状态行必须说清楚，不然「running」看着像在等
		本机 llama-server，用户点了菜单里的「启动/停止前端」也看不出发生了什么
		（2026-09-22 用户报的「没反应」有一半是这个）。
	*/
	bool statusApiEnabled = false;
	bool statusVramLow = false;
	double statusVramFreeGb = 0.0;
	MelderString statusFrontendModel;
	MelderString statusFrontendStatus;
	MelderString statusApiStatus;
	char32 theAiProjectDirectoryBuffer [Preferences_STRING_BUFFER_SIZE];
	constexpr conststring32 defaultFrontendModel = U"Qwen3.5-0.8B-Q4_K_M.gguf";
	/*
		用户在编辑器里手动拖出来的选区。只在「编辑器还开着」时才算数：
		编辑器关掉之后 editors[] 里的那个指针会被清成 null，这里自然就失效了。
	*/
	Thing theNotedEditor = nullptr;
	Thing theNotedEditorObject = nullptr;
	double theNotedSelectionStart = 0.0, theNotedSelectionEnd = 0.0;
	std::optional<double> theNotedVotContextStart, theNotedVotContextEnd;

	struct VOTJobRecord {
		std::filesystem::path directory;
		std::filesystem::path manifestPath, pcmPath, wavPath, requestPath, statePath;
		std::filesystem::path preparedPath, acousticResultPath;
		integer objectId { 0 };
		integer targetStartSample { 0 }, targetEndSample { 0 };
		integer contextStartSample { 0 }, contextEndSample { 0 };
		double burstThresholdDb { 6.0 }, pitchFloorHz { 75.0 };
		std::string mode;
		bool completionStarted { false };
	};
	std::unordered_map<std::string, VOTJobRecord> votEditorJobs;
	std::atomic <uint64_t> nextVotJobId { 0 };

	std::string jsonQuoteUtf8 (const std::string &value) {
		std::string result = "\"";
		for (const unsigned char character : value) {
			switch (character) {
				case '\\': result += "\\\\"; break;
				case '"': result += "\\\""; break;
				case '\n': result += "\\n"; break;
				case '\r': result += "\\r"; break;
				case '\t': result += "\\t"; break;
				default:
					if (character < 0x20) {
						static constexpr char hex [] = "0123456789abcdef";
						result += "\\u00";
						result += hex [character >> 4];
						result += hex [character & 15];
					} else {
						result += (char) character;
					}
			}
		}
		result += '"';
		return result;
	}

	std::string jsonQuote32 (conststring32 value) {
		autostring8 utf8 = Melder_32to8 (value ? value : U"");
		return jsonQuoteUtf8 (utf8 ? utf8.get() : "");
	}

	std::string jsonNumber32 (double value) {
		autostring8 utf8 = Melder_32to8 (Melder_double (value));
		return utf8 ? utf8.get() : "0";
	}

	std::string jsonObjectField (const std::string &json, const std::string &name) {
		const std::string key = "\"" + name + "\"";
		const size_t keyPosition = json.find (key);
		if (keyPosition == std::string::npos)
			return {};
		const size_t begin = json.find ('{', keyPosition + key.size());
		if (begin == std::string::npos)
			return {};
		bool inString = false, escaped = false;
		integer depth = 0;
		for (size_t position = begin; position < json.size(); position ++) {
			const char character = json [position];
			if (inString) {
				if (escaped)
					escaped = false;
				else if (character == '\\')
					escaped = true;
				else if (character == '"')
					inString = false;
				continue;
			}
			if (character == '"') {
				inString = true;
			} else if (character == '{') {
				depth ++;
			} else if (character == '}' && -- depth == 0) {
				return json.substr (begin, position - begin + 1);
			}
		}
		return {};
	}

	std::string utf8From32 (conststring32 value) {
		autostring8 utf8 = Melder_32to8 (value ? value : U"");
		return utf8 ? utf8.get() : "";
	}

	bool notedSelectionMatches (integer iobject, Daata object) {
		if (! theNotedEditor || theNotedEditorObject != (Thing) object)
			return false;
		if (! (theNotedSelectionEnd > theNotedSelectionStart))
			return false;   // 只点了一下光标，没拖选
		for (integer ieditor = 0; ieditor < praat_MAXNUM_EDITORS; ieditor ++)
			if ((Thing) theCurrentPraatObjects -> list [iobject]. editors [ieditor] == theNotedEditor)
				return true;
		return false;
	}

	std::string formatSelectionSeconds (double value) {
		std::ostringstream text;
		text << std::fixed << std::setprecision (17) << value;
		return text. str();
	}

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

	long praatProcessId () {
		/*
			当前 Praat 的进程号：写进 chat_context.tsv，供对话窗口判断这份列表
			是不是正在跑的这个 Praat 写的（C5）。
		*/
		#if defined (_WIN32)
			return static_cast <long> (GetCurrentProcessId ());
		#else
			return static_cast <long> (getpid ());
		#endif
	}

	std::string buildChatContext () {
		std::ostringstream text;
		text << "id\tclass\tname\tselected\tsel_start\tsel_end\tcontext_start\tcontext_end\n";
		if (theCurrentPraatObjects) {
			for (integer iobject = 1; iobject <= theCurrentPraatObjects -> n; iobject ++) {
				Daata object = theCurrentPraatObjects -> list [iobject]. object;
				if (! object)
					continue;
				text
					<< theCurrentPraatObjects -> list [iobject]. id << '\t'
					<< cleanContextField (Thing_className (object)) << '\t'
					<< cleanContextField (theCurrentPraatObjects -> list [iobject]. name. get()) << '\t'
					<< (theCurrentPraatObjects -> list [iobject]. isSelected ? "1" : "0");
				if (notedSelectionMatches (iobject, object))
					text
						<< '\t' << formatSelectionSeconds (theNotedSelectionStart)
						<< '\t' << formatSelectionSeconds (theNotedSelectionEnd)
						<< '\t' << (theNotedVotContextStart ? formatSelectionSeconds (theNotedVotContextStart.value()) : "")
						<< '\t' << (theNotedVotContextEnd ? formatSelectionSeconds (theNotedVotContextEnd.value()) : "");
				else
					text << "\t\t\t\t";   // 没有圈选就留空四列，行数与表头保持一致
				text << '\n';
			}
		}
		return text. str();
	}

	void writeChatContext (bool force = false) {
		static std::string previousContext;
		/*
			末尾写上自己的进程号（C5）：对话窗口看到标记就是当前这个 Praat，就
			知道这份列表是最新的，不用每条消息再投一条空脚本刷新——省一次完整
			往返（投递 + 等待），也少一次被模态窗口挡住的机会。
			对这个文件的解析会忽略这一行（praat_ai.tools.parse_object_context）。
		*/
		const std::string context = buildChatContext ()
			+ "# praat-pid=" + std::to_string (praatProcessId ()) + "\n";
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

	/*
		跑一个「脱离」的 Python 启动器：Praat 只等它几百毫秒（它把真正的窗口进程
		拉起来就退出了）。

		顺便告诉那个窗口「是谁启动了你」——Praat 的进程号 + Praat.exe 路径。前端
		按这两条线索盯着：Praat 关掉之后，对话窗口和 API 配置小窗都自己退出
		（见 ai/praat_ai/parent_watch.py，用户 2026-09-21 报的 bug）。
	*/
	void runDetachedLauncher (const std::filesystem::path &launcher) {
		const std::string launcher8 = launcher. u8string();
		const std::string directory8 = projectDirectoryPath(). u8string();
		autostring32 launcher32 = Melder_8to32_e (launcher8. c_str());
		autostring32 directory32 = Melder_8to32_e (directory8. c_str());
		const std::filesystem::path executable = praatExecutablePath ();
		#if defined (_WIN32)
			const std::wstring pidText = std::to_wstring (praatProcessId ());
			SetEnvironmentVariableW (
				L"PRAAT_AI_PRAAT_EXECUTABLE",
				executable. empty() ? nullptr : executable. wstring(). c_str()
			);
			SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_PID", pidText. c_str());
		#endif
		try {
			praat_runPythonScriptFile (
				launcher32 ? launcher32. get() : U"",
				directory32 ? directory32. get() : nullptr
			);
		} catch (...) {
			#if defined (_WIN32)
				SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_EXECUTABLE", nullptr);
				SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_PID", nullptr);
			#endif
			throw;
		}
		#if defined (_WIN32)
			SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_EXECUTABLE", nullptr);
			SetEnvironmentVariableW (L"PRAAT_AI_PRAAT_PID", nullptr);
		#endif
	}

	void launchAiChatWindow () {
		writeChatContext (true);
		runDetachedLauncher (projectDirectoryPath() / "start_ai_chat.py");
	}

	void launchApiSettingsWindow () {
		/*
			「前端 → API 配置…」：新起一个**独立**进程显示那个 Tk 窗口。

			不能走 runControlCommand()：那条路 = praat_runPythonScriptFile()，
			Praat 会一直读子进程的标准输出直到子进程退出；而这个窗口要等用户点
		关闭才退出，于是 Praat 的主线程整个被堵住（实测窗口 Responding=False）：
			缩一下语图窗口或对象窗口就成了幽灵窗口，再点关闭就是「未响应 → 结束
			进程」，用户看到的就是崩溃（2026-09-21 用户报的）。
		*/
		runDetachedLauncher (projectDirectoryPath() / "start_api_settings.py");
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
	statusApiEnabled = jsonBoolField (* text, "api_enabled", false);
	MelderString_empty (& statusApiStatus);
	if (statusApiEnabled) {
		const std::string apiModel = jsonStringField (* text, "api_model");
		autostring32 apiModel32 = Melder_8to32_e (apiModel. c_str());
		MelderString_append (
			& statusApiStatus,
			U"API 模式（",
			apiModel32 && apiModel32. get() [0] ? apiModel32. get() : U"云端模型",
			U"，不需要本机模型服务）"
		);
	}
	return statusSuccess;
}

conststring32 PraatAiControl_getFrontendModel () {
	return statusFrontendModel. string ? statusFrontendModel. string : defaultFrontendModel;
}

conststring32 PraatAiControl_getFrontendStatus () {
	if (statusApiEnabled && statusApiStatus. string)
		return statusApiStatus. string;
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

void PraatAiControl_configureApi () {
	/*
		「前端 → API 配置…」：打开那个填 API key 的小窗口。

		窗口本身是 Python + Tk 的（ai/praat_ai/api_settings.py）：填服务商、Base URL、
		模型名和 key，点「测试连接」确认，保存后写进 ai_config.json 的 api 节，
		前端下一次请求就改用云端模型（本地 llama-server 的配置原样留着）。

		窗口要跑在**独立进程**里（launchApiSettingsWindow），不能让 Praat 等它——
		否则窗口开着的时候 Praat 整个不响应，缩窗就变幽灵窗口（见那个函数的注释）。
	*/
	launchApiSettingsWindow ();
	PraatAiControl_refreshStatus ();
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

void PraatAiControl_refreshChatContext (bool force) {
	if (Melder_batch)
		return;   // 批处理里没有对话窗口
	writeChatContext (force);   // 默认内容没变化时不重复写盘
}

void PraatAiControl_reportChatScriptFailure (conststring32 message) {
	/*
		app 发来的脚本报错时走这里（sys/praat.cpp 的 cb_userMessage）。

		为什么不直接 Melder_flushError：Windows 上那会开一个
		MessageBox (MB_OK | MB_TOPMOST)，它自带消息循环。用户不点掉它，
		对话窗口就看不到「这一条为什么失败」——只会一条条等到 25 秒超时，
		而且错误原文（英文）还留在那个框里，前端读不到（guide.md §8.5、§8.9）。

		这里改成：错误写进对话窗口读的结果文件（一行，前端直接显示），
		再补一句完成标记，让前端立刻结束等待而不是干等超时。
	*/
	const std::filesystem::path runtimeDirectory = projectDirectoryPath() / "runtime";
	std::error_code error;
	std::filesystem::create_directories (runtimeDirectory, error);
	autostring8 message8 = Melder_32to8 (message ? message : U"");
	const std::string raw = message8 ? message8. get() : "";
	/*
		结果文件一行一条结果，所以把多行错误压成一行：去掉空行、每行首尾空白，
		用 " | " 连起来（Praat 的错误里通常有「命令原文 / 第几行 / 脚本名」三段）。
	*/
	std::string text = "脚本没跑完（Praat 报错，后面的消息不会被它挡住）：";
	std::istringstream lines (raw);
	std::string line;
	bool first = true;
	while (std::getline (lines, line)) {
		const size_t begin = line. find_first_not_of (" \t\r");
		if (begin == std::string::npos)
			continue;
		const size_t end = line. find_last_not_of (" \t\r");
		if (! first)
			text += " | ";
		text += line. substr (begin, end - begin + 1);
		first = false;
	}
	if (first)   // 一个字符都没有（理论上不会）
		text += "（Praat 没有给出错误文字）";
	{
		std::ofstream result (runtimeDirectory / "chat_result.tsv", std::ios::binary | std::ios::app);
		if (result. is_open()) {
			result << text << "\n";
		}
	}
	{
		std::ofstream state (runtimeDirectory / "chat_state.txt", std::ios::binary | std::ios::app);
		if (state. is_open()) {
			state << "done\n";
		}
	}
	{
		/*
			另写一份原始错误给前端读：前端看到这个文件就知道「这一条是失败的」，
			而不是把错误行当成正常结果（chat.py 的 _read_failure）。
		*/
		std::ofstream failure (runtimeDirectory / "chat_failure.txt", std::ios::binary | std::ios::trunc);
		if (failure. is_open()) {
			failure << raw << "\n";
		}
	}
}

void PraatAiControl_noteEditorSelection (Thing editor, Thing object, double start, double end,
		std::optional<double> contextStart, std::optional<double> contextEnd)
{
	if (Melder_batch)
		return;
	const bool sameEditor = theNotedEditor == editor && theNotedEditorObject == object;
	theNotedEditor = editor;
	theNotedEditorObject = object;
	theNotedSelectionStart = start;
	theNotedSelectionEnd = end;
	if (contextStart.has_value() && contextEnd.has_value() &&
		std::isfinite (contextStart.value()) && std::isfinite (contextEnd.value()) &&
		contextStart.value() < contextEnd.value())
	{
		theNotedVotContextStart = contextStart;
		theNotedVotContextEnd = contextEnd;
	} else if (! sameEditor) {
		theNotedVotContextStart.reset();
		theNotedVotContextEnd.reset();
	}
	writeChatContext ();   // 内容没变化时不会重复写盘
}

void PraatAiControl_clearEditorVOTContext (Thing editor, Thing object) {
	if (Melder_batch || theNotedEditor != editor || theNotedEditorObject != object)
		return;
	theNotedVotContextStart.reset();
	theNotedVotContextEnd.reset();
	writeChatContext ();
}

std::string PraatAiControl_submitVOTJob (Thing audioObject, integer objectId,
		integer targetStartSample, integer targetEndSample,
		integer contextStartSample, integer contextEndSample,
		conststring32 mode, conststring32 language, conststring32 transcript,
		conststring32 phonemes, integer targetPhoneIndex,
		double burstThresholdDb, double pitchFloorHz,
		std::optional<integer> manualBurstSample,
		std::optional<integer> manualOnsetSample)
{
	Melder_require (audioObject && objectId > 0, U"VOT analysis requires a live Sound or LongSound object.");
	Melder_require (std::isfinite (burstThresholdDb) && std::isfinite (pitchFloorHz),
		U"VOT acoustic parameters must be finite.");
	Melder_require ((bool) mode && (str32equ (mode, U"model_assisted") ||
		str32equ (mode, U"acoustic_only") || str32equ (mode, U"manual")),
		U"VOT mode must be model_assisted, acoustic_only, or manual.");
	const bool isLongSound = Thing_isa (audioObject, classLongSound);
	const bool isSound = Thing_isa (audioObject, classSound);
	Melder_require (isLongSound || isSound, U"VOT analysis supports Sound and LongSound objects only.");
	Melder_require (targetStartSample >= contextStartSample && targetStartSample < targetEndSample &&
		targetEndSample <= contextEndSample,
		U"VOT target sample range must lie inside the fixed context range.");
	Melder_require (manualBurstSample.has_value() == manualOnsetSample.has_value(),
		U"Manual VOT needs both boundary sample indices.");

	const uint64_t serial = nextVotJobId.fetch_add (1, std::memory_order_relaxed);
	const auto clockValue = std::chrono::steady_clock::now().time_since_epoch().count();
	const std::string jobId = "vot-" + std::to_string (objectId) + "-" +
		std::to_string (clockValue) + "-" + std::to_string (serial);
	const std::filesystem::path jobDirectory = projectDirectoryPath() / "runtime" / "vot_jobs" / jobId;
	std::error_code filesystemError;
	std::filesystem::create_directories (jobDirectory, filesystemError);
	Melder_require (! filesystemError, U"Could not create the VOT job directory.");
	VOTJobRecord record;
	record.directory = jobDirectory;
	record.manifestPath = jobDirectory / "snapshot.json";
	record.pcmPath = jobDirectory / "snapshot.f64le";
	record.wavPath = jobDirectory / "alignment.wav";
	record.requestPath = jobDirectory / "request.json";
	record.statePath = jobDirectory / "state.json";
	record.preparedPath = jobDirectory / "prepared.json";
	record.acousticResultPath = jobDirectory / "native-acoustic.tsv";
	record.objectId = objectId;
	record.targetStartSample = targetStartSample;
	record.targetEndSample = targetEndSample;
	record.contextStartSample = contextStartSample;
	record.contextEndSample = contextEndSample;
	record.burstThresholdDb = burstThresholdDb;
	record.pitchFloorHz = pitchFloorHz;
	record.mode = utf8From32 (mode);

	autostring32 manifestName = Melder_8to32_e (record.manifestPath.u8string().c_str());
	autostring32 pcmName = Melder_8to32_e (record.pcmPath.u8string().c_str());
	autostring32 wavName = Melder_8to32_e (record.wavPath.u8string().c_str());
	if (isLongSound)
		praat_LongSound_writeVOTAudioSnapshot (static_cast <LongSound> (audioObject), objectId,
			contextStartSample, contextEndSample, manifestName.get(), pcmName.get(), wavName.get());
	else
		praat_Sound_writeVOTAudioSnapshot (static_cast <Sound> (audioObject), objectId,
			contextStartSample, contextEndSample, manifestName.get(), pcmName.get(), wavName.get());

	const SampledXY sampled = static_cast <SampledXY> (audioObject);
	const std::string requestIdJson = jsonQuoteUtf8 (jobId);
	autoMelderString phoneArray;
	MelderString_append (& phoneArray, U"[");
	bool firstPhone = true;
	std::u32string phone;
	for (const char32 *character = phonemes ? phonemes : U"";; character ++) {
		if (*character && *character != U' ' && *character != U'\t' && *character != U'\r' && *character != U'\n') {
			phone.push_back (*character);
			continue;
		}
		if (! phone.empty()) {
			if (! firstPhone)
				MelderString_append (& phoneArray, U",");
			const std::string phoneJson = jsonQuote32 (phone.c_str());
			autostring32 phoneJson32 = Melder_8to32_e (phoneJson.c_str());
			MelderString_append (& phoneArray, phoneJson32.get());
			firstPhone = false;
			phone.clear();
		}
		if (! *character)
			break;
	}
	MelderString_append (& phoneArray, U"]");
	autostring8 phoneArray8 = Melder_32to8 (phoneArray.string);

	const std::string snapshotKind = isLongSound ? "LongSound" : "Sound";
	const std::string manifestPath8 = record.manifestPath.u8string();
	const std::string pcmPath8 = record.pcmPath.u8string();
	const std::string wavPath8 = record.wavPath.u8string();
	const std::string jobDirectory8 = record.directory.u8string();
	const std::string sampleRate = jsonNumber32 (1.0 / sampled -> dx);
	const std::string timeOrigin = jsonNumber32 (
		isLongSound ? static_cast <LongSound> (audioObject) -> x1 + contextStartSample * sampled -> dx :
		static_cast <Sound> (audioObject) -> x1 + contextStartSample * sampled -> dx);
	const std::string parametersJson = "{\"burst_threshold_db\":" + jsonNumber32 (burstThresholdDb) +
		",\"pitch_floor_hz\":" + jsonNumber32 (pitchFloorHz) +
		",\"pitch_ceiling_hz\":500.0}";
	const std::string phonemeValues = phoneArray8 ? phoneArray8.get() : "[]";
	std::ofstream request (record.requestPath, std::ios::binary | std::ios::trunc);
	Melder_require (request.is_open(), U"Could not create the VOT editor request.");
	request
		<< "{\"request_id\":" << requestIdJson
		<< ",\"job_directory\":" << jsonQuoteUtf8 (jobDirectory8)
		<< ",\"audio_snapshot\":{\"object_id\":" << objectId
		<< ",\"source_kind\":" << jsonQuoteUtf8 (snapshotKind)
		<< ",\"sample_rate_hz\":" << sampleRate
		<< ",\"channels\":" << (isLongSound ? static_cast <LongSound> (audioObject) -> numberOfChannels : static_cast <Sound> (audioObject) -> ny)
		<< ",\"sample_count\":" << contextEndSample - contextStartSample
		<< ",\"snapshot_start_sample\":" << contextStartSample
		<< ",\"time_origin_seconds\":" << timeOrigin << "}"
		<< ",\"snapshot_paths\":{\"manifest\":" << jsonQuoteUtf8 (manifestPath8)
		<< ",\"pcm\":" << jsonQuoteUtf8 (pcmPath8)
		<< ",\"wav\":" << jsonQuoteUtf8 (wavPath8) << "}"
		<< ",\"target_range\":[" << targetStartSample << "," << targetEndSample << "]"
		<< ",\"acoustic_context_range\":[" << contextStartSample << "," << contextEndSample << "]"
		<< ",\"alignment_context_range\":[" << contextStartSample << "," << contextEndSample << "]"
		<< ",\"language\":" << jsonQuote32 (language)
		<< ",\"transcript\":" << jsonQuote32 (transcript)
		<< ",\"phonemes\":" << phonemeValues
		<< ",\"target_phone_index\":" << targetPhoneIndex
		<< ",\"mode\":" << jsonQuoteUtf8 (record.mode)
		<< ",\"parameters\":" << parametersJson
		<< ",\"manual_boundaries\":";
	if (manualBurstSample)
		request << "[" << manualBurstSample.value() << "," << manualOnsetSample.value() << "]";
	else
		request << "null";
	request << "}\n";
	request.close();
	Melder_require (request.good(), U"Could not finish writing the VOT editor request.");
	{
		std::ofstream queued (record.statePath, std::ios::binary | std::ios::trunc);
		queued << "{\"job_id\":" << requestIdJson
			<< ",\"state\":\"queued\",\"stage\":\"queued\",\"progress\":0.0,\"error\":\"\"}\n";
		Melder_require (queued.good(), U"Could not initialize VOT job state.");
	}
	votEditorJobs.emplace (jobId, record);

	const std::string requestPath8 = record.requestPath.u8string();
	const std::string projectPath8 = projectDirectoryPath().u8string();
	autostring32 launcherPath = Melder_8to32_e (	(projectDirectoryPath() / "praat_ai" / "launch_vot_worker.py").u8string().c_str());
	autostring32 projectPath = Melder_8to32_e (projectPath8.c_str());
	setEnvironmentUtf8 ("PRAAT_AI_VOT_REQUEST", requestPath8);
	try {
		praat_runPythonScriptFile (launcherPath.get(), projectPath.get());
	} catch (...) {
		clearEnvironmentUtf8 ("PRAAT_AI_VOT_REQUEST");
		votEditorJobs.erase (jobId);
		throw;
	}
	clearEnvironmentUtf8 ("PRAAT_AI_VOT_REQUEST");
	return jobId;
}

PraatAiVOTJobStatus PraatAiControl_pollVOTJob (conststring32 jobId32) {
	const std::string jobId = utf8From32 (jobId32);
	auto found = votEditorJobs.find (jobId);
	Melder_require (found != votEditorJobs.end(), U"Unknown VOT editor job.");
	VOTJobRecord &job = found -> second;
	const std::optional<std::string> contents = readTextFile (job.statePath);
	const std::string stateJson = contents.value_or (
		"{\"state\":\"queued\",\"stage\":\"starting\",\"progress\":0.0,\"error\":\"\"}");
	PraatAiVOTJobStatus status;
	status.state = jsonStringField (stateJson, "state", "queued");
	status.stage = jsonStringField (stateJson, "stage", "queued");
	status.error = jsonStringField (stateJson, "error", "");
	status.progress = std::clamp (jsonNumberField (stateJson, "progress", 0.0), 0.0, 1.0);
	const std::string alignedJson = jsonObjectField (stateJson, "aligned_phone");
	if (! alignedJson.empty()) {
		const double alignedStart = jsonNumberField (alignedJson, "start_sample", -1.0);
		const double alignedEnd = jsonNumberField (alignedJson, "end_sample", -1.0);
		if (alignedStart >= 0.0 && alignedEnd > alignedStart) {
			status.alignedStartSample = Melder_iround (alignedStart);
			status.alignedEndSample = Melder_iround (alignedEnd);
		}
	}
	if (status.state == "ready_for_acoustics" && ! job.completionStarted) {
		job.completionStarted = true;
		try {
			const integer alignedStart = status.alignedStartSample.value_or (-1);
			const integer alignedEnd = status.alignedEndSample.value_or (-1);
			const std::string parametersJson = "{\"burst_threshold_db\":" + jsonNumber32 (job.burstThresholdDb) +
				",\"pitch_floor_hz\":" + jsonNumber32 (job.pitchFloorHz) +
				",\"pitch_ceiling_hz\":500.0}";
			autostring32 manifestPath = Melder_8to32_e (job.manifestPath.u8string().c_str());
			autostring32 pcmPath = Melder_8to32_e (job.pcmPath.u8string().c_str());
			autostring32 resultPath = Melder_8to32_e (job.acousticResultPath.u8string().c_str());
			autostring32 parameters = Melder_8to32_e (parametersJson.c_str());
			praat_VOT_analyseSnapshotAndWriteResult (manifestPath.get(), pcmPath.get(),
				job.targetStartSample, job.targetEndSample, job.contextStartSample, job.contextEndSample,
				alignedStart, alignedEnd, parameters.get(), resultPath.get());
			const std::string script8 = (projectDirectoryPath() / "praat_ai" / "complete_vot_editor_job.py").u8string();
			const std::string directory8 = projectDirectoryPath().u8string();
			autostring32 script32 = Melder_8to32_e (script8.c_str());
			autostring32 directory32 = Melder_8to32_e (directory8.c_str());
			setEnvironmentUtf8 ("PRAAT_AI_VOT_PREPARED", job.preparedPath.u8string());
			setEnvironmentUtf8 ("PRAAT_AI_VOT_CPP_RESULT", job.acousticResultPath.u8string());
			setEnvironmentUtf8 ("PRAAT_AI_VOT_STATE", job.statePath.u8string());
			try {
				praat_runPythonScriptFile (script32.get(), directory32.get());
			} catch (...) {
				clearEnvironmentUtf8 ("PRAAT_AI_VOT_PREPARED");
				clearEnvironmentUtf8 ("PRAAT_AI_VOT_CPP_RESULT");
				clearEnvironmentUtf8 ("PRAAT_AI_VOT_STATE");
				throw;
			}
			clearEnvironmentUtf8 ("PRAAT_AI_VOT_PREPARED");
			clearEnvironmentUtf8 ("PRAAT_AI_VOT_CPP_RESULT");
			clearEnvironmentUtf8 ("PRAAT_AI_VOT_STATE");
		} catch (MelderError) {
			const std::string error = utf8From32 (Melder_getError());
			Melder_clearError();
			std::ofstream failed (job.statePath, std::ios::binary | std::ios::trunc);
			failed << "{\"job_id\":" << jsonQuoteUtf8 (jobId)
				<< ",\"state\":\"failed\",\"stage\":\"failed\",\"progress\":1.0,\"error\":"
				<< jsonQuoteUtf8 (error) << "}\n";
		} catch (const std::exception &error) {
			std::ofstream failed (job.statePath, std::ios::binary | std::ios::trunc);
			failed << "{\"job_id\":" << jsonQuoteUtf8 (jobId)
				<< ",\"state\":\"failed\",\"stage\":\"failed\",\"progress\":1.0,\"error\":"
				<< jsonQuoteUtf8 (error.what()) << "}\n";
		}
		const std::optional<std::string> completed = readTextFile (job.statePath);
		const std::string finalJson = completed.value_or ("{}");
		status.state = jsonStringField (finalJson, "state", "failed");
		status.stage = jsonStringField (finalJson, "stage", status.state);
		status.error = jsonStringField (finalJson, "error", "");
		status.progress = std::clamp (jsonNumberField (finalJson, "progress", 1.0), 0.0, 1.0);
		status.resultJson = jsonObjectField (finalJson, "result");
	}
	/* Terminal Python results (for example, missing language/model input) can be
	   written before the editor's first poll. Always expose the nested result. */
	if (status.resultJson.empty())
		status.resultJson = jsonObjectField (stateJson, "result");
	return status;
}

bool PraatAiControl_cancelVOTJob (conststring32 jobId32) {
	const std::string jobId = utf8From32 (jobId32);
	auto found = votEditorJobs.find (jobId);
	if (found == votEditorJobs.end())
		return false;
	VOTJobRecord &job = found -> second;
	std::ofstream cancel (job.directory / "cancel", std::ios::binary | std::ios::trunc);
	if (! cancel.is_open())
		return false;
	cancel << "stale\n";
	cancel.close();
	std::ofstream state (job.statePath, std::ios::binary | std::ios::trunc);
	state << "{\"job_id\":" << jsonQuoteUtf8 (jobId)
		<< ",\"state\":\"cancelled\",\"stage\":\"stale\",\"progress\":1.0,"
		<< "\"error\":\"VOT request became stale before completion\"}\n";
	return state.good();
}

/* End of file PraatAiControl.cpp */
