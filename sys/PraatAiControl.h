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
void PraatAiControl_refreshChatContext ();
void PraatAiControl_noteEditorSelection (Thing editor, Thing object, double start, double end);

#endif
