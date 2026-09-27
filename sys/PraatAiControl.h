#ifndef _PraatAiControl_h_
#define _PraatAiControl_h_
/* PraatAiControl.h
 *
 * Local AI frontend integration for Praat.
 */

#include "Thing.h"

#include <optional>
#include <string>

void PraatAiControl_initPreferences ();

conststring32 PraatAiControl_getAlignmentMode ();
void PraatAiControl_setAlignmentMode (conststring32 mode);

bool PraatAiControl_refreshStatus ();
conststring32 PraatAiControl_getFrontendModel ();
conststring32 PraatAiControl_getFrontendStatus ();
conststring32 PraatAiControl_getVramText (bool *low);
void PraatAiControl_chooseFrontendModel ();
/* 「前端 → API 配置…」：打开填 API key 的小窗口（云端大模型，见
   ai/praat_ai/api_settings.py）。 */
void PraatAiControl_configureApi ();
void PraatAiControl_startFrontend ();
void PraatAiControl_stopFrontend ();
void PraatAiControl_runAnalysis ();
/* 重写对话窗口读的对象列表。force=true 时即使内容和上次一样也重写一次
   （app 发来的每条消息之后都用它，见 sys/praat.cpp 的 cb_userMessage）。 */
void PraatAiControl_refreshChatContext (bool force = false);
/* app 发来的脚本没跑完：把错误文字写进对话窗口的结果文件，并补上完成标记
   （不弹模态错误框——那个框会挡住后面所有消息，见 cb_userMessage 的说明）。 */
void PraatAiControl_reportChatScriptFailure (conststring32 message);
/* Optional test-only report of failures swallowed by the SoundEditor VOT form. */
void PraatAiControl_reportVOTEditorDiagnostic (conststring32 message);
void PraatAiControl_noteEditorSelection (Thing editor, Thing object, double start, double end,
	std::optional<double> contextStart = {}, std::optional<double> contextEnd = {});
void PraatAiControl_clearEditorVOTContext (Thing editor, Thing object);

struct PraatAiVOTJobStatus {
	std::string state;
	std::string stage;
	std::string error;
	std::string resultJson;
	double progress { 0.0 };
	std::optional<integer> alignedStartSample;
	std::optional<integer> alignedEndSample;
};

std::string PraatAiControl_submitVOTJob (Thing audioObject, integer objectId,
		integer targetStartSample, integer targetEndSample,
		integer contextStartSample, integer contextEndSample,
		conststring32 mode, conststring32 language, conststring32 transcript,
		conststring32 phonemes, integer targetPhoneIndex,
		double burstThresholdDb, double pitchFloorHz,
		std::optional<integer> manualBurstSample = {},
		std::optional<integer> manualOnsetSample = {});
PraatAiVOTJobStatus PraatAiControl_pollVOTJob (conststring32 jobId);
bool PraatAiControl_cancelVOTJob (conststring32 jobId);

#endif
