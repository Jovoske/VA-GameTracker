// The week's wind line as it stands now (src/windline.ts, feature 22): a copy kept on
// the phone and read hours later never offers tonight's hours that are over. Once an
// hour the server counted as still to come has passed, tonight's part is made again
// from the hours left, by the server's rule (backend forecasting/wind_week.py, and
// tests/test_wind_week.py for its cases): the runs a sit fits in first, the longest
// of them, then a single hour if there is room, two at most, in time order.
// No browser: node tests/wind-line.cjs (esbuild, which Vite brings, reads the .ts).
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path')
const { transformSync } = require('esbuild')

const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'windline.ts'), 'utf8')
const mod = { exports: {} }
new Function('module', 'exports', transformSync(src, { loader: 'ts', format: 'cjs' }).code)(mod, mod.exports)
const { lineNow, hourGone } = mod.exports

// Thursday 24 September 2026, summer time: 19 h on the estate's clock is 17:00 UTC.
const night = '2026-09-24'
const at = (h, day = 0) => new Date(Date.UTC(2026, 8, 24 + day, h - 2)).toISOString()
const local = (h, m = 0) => Date.UTC(2026, 8, 24, h - 2, m)
// A stand's week as the server wrote it at `made` (16:00): right at `right` tonight.
const stand = (right, { days = [], made = local(16), status = 'ok', line, right_tonight = null, noForecast = false } = {}) => ({
  stand: 'Charca', status, line: line ?? 'server line', right_tonight, right_days: days,
  evenings: [0, 1, 2].map((d) => ({
    night: `2026-09-${24 + d}`,
    hours: [17, 18, 19, 20, 21, 22, 23, 24].map((h) => ({
      hour: h, at: at(h, d), gone: Date.parse(at(h, d)) + 3600e3 <= made,
      status: noForecast ? 'no_wind_data' : d === 0 && right.includes(h) ? 'clean' : 'scent_carries',
    })),
  })),
})

// The hour under way still counts; it is over at the top of the next.
assert.equal(hourGone(at(19), local(19, 59)), false)
assert.equal(hourGone(at(19), local(20)), true)

// Nothing the server counted as to come is over: its own line, word for word.
let s = stand([19, 20, 21], { days: ['Sat'], line: 'Right wind for Charca: tonight 19–21 h, Sat', right_tonight: '19–21 h' })
assert.deepEqual(lineNow(s, night, local(16, 50)), { line: s.line, right_tonight: '19–21 h', right_days: ['Sat'] })
assert.equal(lineNow(s, night, local(17, 59)).line, s.line, 'the 17 h hour is still under way')

// Read at 21:30 from the 16:00 copy: 19 and 20 h are over, 21 h is under way.
assert.deepEqual(lineNow(s, night, local(21, 30)), { line: 'Right wind for Charca: tonight 21 h, Sat', right_tonight: '21 h', right_days: ['Sat'] })
// At 22:10 tonight's right hours are all over: only the evenings to come.
assert.equal(lineNow(s, night, local(22, 10)).line, 'Right wind for Charca: Sat')
// And with none to come either, it says so.
assert.equal(lineNow(stand([19, 20, 21]), night, local(22, 10)).line, 'No right wind for Charca this week.')
// After midnight, still Thursday's night, the copy's evening is over.
assert.equal(lineNow(s, night, local(25, 30)).line, 'Right wind for Charca: Sat')

// The sit window before stray hours (review R6FE-2): right at 18, 20 and 22–24, read
// at 18:10 (17 h over): "tonight 18 h and 22–24 h", not "18 h and 20 h".
assert.equal(lineNow(stand([18, 20, 22, 23, 24]), night, local(18, 10)).line, 'Right wind for Charca: tonight 18 h and 22–24 h')
// Two runs a sit fits in and a stray hour: the two runs.
assert.equal(lineNow(stand([18, 20, 21, 23, 24]), night, local(18, 10)).right_tonight, '20–21 h and 23–24 h')
// Three: the two longest, in time order.
assert.equal(lineNow(stand([18, 19, 21, 22, 23]), night, local(18, 10)).right_tonight, '18–19 h and 21–23 h')
// Stray hours only: the first two.
assert.equal(lineNow(stand([18, 20, 22]), night, local(18, 10)).right_tonight, '18 h and 20 h')

// A stand that can't be judged, or a week with no forecast, says so whatever the hour.
const loose = stand([], { status: 'no_position', line: 'Loma isn’t on the map yet, so its wind can’t be judged.' })
assert.equal(lineNow(loose, night, local(22)).line, loose.line)
const none = stand([], { noForecast: true, line: 'No wind forecast for the week yet.' })
assert.equal(lineNow(none, night, local(22)).line, none.line)

// A copy made after midnight starts at the coming evening: nothing of it is tonight's.
const coming = stand([19], { line: 'Right wind for Charca: Fri' })
assert.equal(lineNow(coming, '2026-09-23', local(1)).line, coming.line)

console.log('PASS: the week line keeps the server’s words until an hour passes, then names only the hours left, the sit window before stray hours, and says why when it can’t judge.')
