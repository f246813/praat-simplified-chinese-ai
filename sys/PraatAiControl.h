#ifndef _PraatAiControl_h_
#define _PraatAiControl_h_
/* PraatAiControl.h
 *
 * Local AI frontend integration for Praat.
 */

#include "Gui.h"
#include "Thing.h"

void PraatAiControl_initPreferences ();

conststring32 PraatAiControl_getAlignmentMode ();
void PraatAiControl_setAlignmentMode (conststring32 mode);

bool PraatAiControl_refreshStatus ();
conststring32 PraatAiControl_getFrontendModel ();
conststring32 PraatAiControl_getFrontendStatus ();
conststring32 PraatAiControl_getVramText (bool *low);
void PraatAiControl_chooseFrontendModel ();
void PraatAiControl_startFrontend ();
void PraatAiControl_stopFrontend ();
void PraatAiControl_runAnalysis ();
/* 重写对话窗口读的对象列表。force=true 时即使内容和上次一样也重写一次
   （app 发来的每条消息之后都用它，见 sys/praat.cpp 的 cb_userMessage）。 */
void PraatAiControl_refreshChatContext (bool force = false);
void PraatAiControl_noteEditorSelection (Thing editor, Thing object, double start, double end);

#endif
