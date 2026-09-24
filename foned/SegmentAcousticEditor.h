#ifndef _SegmentAcousticEditor_h_
#define _SegmentAcousticEditor_h_

#include "Editor.h"
#include "LongSound.h"
#include "SegmentAcousticAnalysis.h"

Thing_define (SegmentAcousticEditor, Editor) {
	TargetReferenceSegment selection;
	void *d_privateState { nullptr };

	void v9_destroy () noexcept override;
	void v1_info () override;
	void v_createChildren () override;
	void v_createMenus () override;
};

autoSegmentAcousticEditor SegmentAcousticEditor_create (
	Sound initialTargetSound, LongSound initialTargetLongSound,
	std::optional<integer> initialObjectId, conststring32 initialSourceName,
	double initialStartTime, double initialEndTime
);

#endif
