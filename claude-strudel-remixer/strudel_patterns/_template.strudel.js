// Remix template - copy to strudel_patterns/<track>.strudel.js and fill in from analysis/<track>.*.json
// Source:   <track file>
// Tempo:    120 BPM            (analysis tempo.bpm)
// Key:      A minor            (vocals key.strudel_scale - the harmony follows the VOCAL, not the full mix)
// Length:   64 bars            (analysis strudel.bars)
// Analyzed: YYYY-MM-DD
//
// Plays as-is in https://strudel.cc. The vocal track is muted (_$:) until the stems are served:
//   npx --yes @strudel/sampler --dir separated/htdemucs
// The first play only downloads the stem and skips it - stop and play again.

setcpm(120/4) // 4/4: one cycle = one bar

// --two-stems=vocals output; for 4 stems use drums: 'drums.wav', bass: 'bass.wav', other: 'other.wav'
samples({ vocals: 'vocals.wav', instrumental: 'no_vocals.wav' }, 'http://localhost:5432/<track>/')

// Drums
$: s("bd*4, [~ cp]*2, [~ hh]*4, [~ ~ ~ oh]")
  .bank("RolandTR909")
  .gain(0.9)

// Bass - scale degrees, one chord root per bar: i - VI - III - VII
$: n("<[0 7]*4 [5 12]*4 [2 9]*4 [6 13]*4>")
  .scale("A1:minor")
  .s("sawtooth")
  .lpf(600)
  .gain(0.5)

// Chords - same progression as the bass
$: chord("<Am F C G>")
  .voicing()
  .s("sawtooth")
  .struct("[~ x]*2")
  .lpf(1800)
  .attack(0.01)
  .release(0.2)
  .room(0.4)
  .gain(0.3)

// Lead
$: n("<[0 2 4 ~ 4 2 ~ ~] [0 2 4 6 7 ~ 6 4]>")
  .scale("A4:minor")
  .s("triangle")
  .delay(0.25)
  .gain(0.25)

// Original vocal, one event per song length so it plays at its own speed and pitch.
// .begin() skips the audio before the first beat: tempo.first_beat_sec / duration_sec
_$: s("vocals")
  .slow(64)
  .begin(0)
  .gain(1)

// Vocal chops: with splice(<bars>, ...) each slice is one bar, played at tempo
_$: s("vocals")
  .splice(64, "<16 17 16 [18 19]>")
  .room(0.3)
  .gain(0.8)
