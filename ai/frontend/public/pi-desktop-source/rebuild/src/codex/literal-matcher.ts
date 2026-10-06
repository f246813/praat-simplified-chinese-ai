// SPDX-License-Identifier: Apache-2.0
// LiteralMatcher::find_ranges, openai/codex ab452649,
// codex-rs/thread-store/src/local/thread_history/search.rs.
// Rust -> TypeScript: UTF-8 byte offsets become DOM UTF-16 offsets. Preserve
// non-overlapping literal matches and the upstream linear two-pointer mapping.
export function literalMatchRanges(text:string,needle:string,limit=500):[number,number][] {
  const lowercaseNeedle=needle.toLowerCase();
  if(!lowercaseNeedle||limit<=0)return [];
  const lowercaseText=text.toLowerCase();
  const spans:{lowerStart:number;lowerEnd:number;start:number;end:number}[]=[];
  // Ordinary case conversion needs no offset translation or span allocation.
  if(lowercaseText.length!==text.length){
    let originalStart=0,lowercaseStart=0;
    for(const character of text){
      const lowercaseEnd=lowercaseStart+character.toLowerCase().length;
      spans.push({lowerStart:lowercaseStart,lowerEnd:lowercaseEnd,start:originalStart,end:originalStart+character.length});
      originalStart+=character.length;lowercaseStart=lowercaseEnd;
    }
  }
  const ranges:[number,number][]=[];
  let from=0,startSpan=0,endSpan=0;
  while(ranges.length<limit){
    const start=lowercaseText.indexOf(lowercaseNeedle,from);
    if(start<0)break;
    const end=start+lowercaseNeedle.length;
    if(spans.length){
      while(spans[startSpan].lowerEnd<=start)startSpan++;
      while(spans[endSpan].lowerEnd<=end-1)endSpan++;
      ranges.push([spans[startSpan].start,spans[endSpan].end]);
    } else ranges.push([start,end]);
    from=end;
  }
  return ranges;
}
