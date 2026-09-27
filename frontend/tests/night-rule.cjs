// The app's night rule (src/night.ts) across the clock changes: a night runs 06:00 to
// 06:00 on the estate's wall clock (Europe/Madrid), as the server counts it. Tonight
// calls a plan made before this morning's 06:00 "made for last night", and Stands
// drops an earlier night's reservations, so one hour off at a clock change would
// show last night's copy as tonight's for an hour, or tonight's as last night's.
// A sit started and not ended is on while its night lasts; after 06:00 only a dawn
// sit (reserved before 06:00, started from 03:00) is, for 6 hours, as the server's
// routes_stands._live says. An evening sit nobody ended must be over at 06:00.
// No browser: node tests/night-rule.cjs (esbuild, which Vite brings, reads the .ts).
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path')
const { transformSync } = require('esbuild')

const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'night.ts'), 'utf8')
const mod = { exports: {} }
new Function('module', 'exports', transformSync(src, { loader: 'ts', format: 'cjs' }).code)(mod, mod.exports)
const { nightOf, fromEarlierNight, nightBefore, startedSitIsOn } = mod.exports

// On each clock-change morning, 05:59 is still the night before and 06:00 is the new one.
const cases = [
  // 25 Oct 2026: 03:00 CEST goes back to 02:00 CET, so 06:00 is 05:00 UTC.
  ['2026-10-25T04:59:00Z', '2026-10-24', '25 Oct 05:59 CET'],
  ['2026-10-25T05:00:00Z', '2026-10-25', '25 Oct 06:00 CET'],
  ['2026-10-25T00:30:00Z', '2026-10-24', '25 Oct 02:30 CEST, the first time'],
  ['2026-10-25T01:30:00Z', '2026-10-24', '25 Oct 02:30 CET, the second time'],
  ['2026-10-24T03:59:00Z', '2026-10-23', '24 Oct 05:59 CEST'],
  ['2026-10-24T04:00:00Z', '2026-10-24', '24 Oct 06:00 CEST'],
  // 29 Mar 2026: 02:00 CET jumps to 03:00 CEST, so 06:00 is 04:00 UTC.
  ['2026-03-29T03:59:00Z', '2026-03-28', '29 Mar 05:59 CEST'],
  ['2026-03-29T04:00:00Z', '2026-03-29', '29 Mar 06:00 CEST'],
  ['2026-03-29T00:59:00Z', '2026-03-28', '29 Mar 01:59 CET, just before the jump'],
  ['2026-03-29T01:00:00Z', '2026-03-28', '29 Mar 03:00 CEST, just after it'],
  ['2026-03-28T04:59:00Z', '2026-03-27', '28 Mar 05:59 CET'],
  ['2026-03-28T05:00:00Z', '2026-03-28', '28 Mar 06:00 CET'],
]
for (const [utc, night, what] of cases) assert.equal(nightOf(utc), night, what)

// Every 5 minutes through both weekends, against the rule said another way: the
// Madrid calendar date, or the day before when the Madrid hour is before 6.
const madrid = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23' })
const expected = (t) => {
  const p = Object.fromEntries(madrid.formatToParts(new Date(t)).map((x) => [x.type, x.value]))
  const day = Date.UTC(+p.year, +p.month - 1, +p.day) - (+p.hour < 6 ? 86_400_000 : 0)
  return new Date(day).toISOString().slice(0, 10)
}
let checked = 0
for (const [from, to] of [['2026-10-23T12:00:00Z', '2026-10-26T12:00:00Z'], ['2026-03-27T12:00:00Z', '2026-03-30T12:00:00Z']]) {
  for (let t = Date.parse(from); t <= Date.parse(to); t += 5 * 60_000, checked++) {
    assert.equal(nightOf(t), expected(t), new Date(t).toISOString())
  }
}

// A plan (or a saved copy of the stands) made at 05:59 is last night's by 06:00;
// one made the evening before is still tonight's at 05:30 after the jump.
assert.equal(fromEarlierNight('2026-10-25T04:59:00Z', Date.parse('2026-10-25T05:00:00Z')), true)
assert.equal(fromEarlierNight('2026-10-25T05:00:00Z', Date.parse('2026-10-25T20:00:00Z')), false)
assert.equal(fromEarlierNight('2026-03-28T20:00:00Z', Date.parse('2026-03-29T03:30:00Z')), false)
assert.equal(fromEarlierNight('2026-03-28T20:00:00Z', Date.parse('2026-03-29T04:00:00Z')), true)

assert.equal(nightBefore('2026-03-01'), '2026-02-28')
assert.equal(nightBefore('2026-09-27', 3), '2026-09-24')

// [night, started, now, on?, what]
const sits = [
  // A normal autumn morning (CEST, UTC+2).
  ['2026-09-26', '2026-09-26T19:00:00Z', '2026-09-27T03:59:00Z', true, 'evening sit, 05:59'],
  ['2026-09-26', '2026-09-26T19:00:00Z', '2026-09-27T04:00:00Z', false, 'evening sit nobody ended, 06:00'],
  ['2026-09-26', '2026-09-27T03:30:00Z', '2026-09-27T05:30:00Z', true, 'dawn sit from 05:30, 07:30'],
  ['2026-09-26', '2026-09-27T03:30:00Z', '2026-09-27T09:29:00Z', true, 'dawn sit, 5 h 59 in'],
  ['2026-09-26', '2026-09-27T03:30:00Z', '2026-09-27T09:30:00Z', false, 'dawn sit, 6 h in'],
  ['2026-09-26', '2026-09-27T01:00:00Z', '2026-09-27T05:30:00Z', true, 'started 03:00: a dawn sit'],
  ['2026-09-26', '2026-09-27T00:59:00Z', '2026-09-27T05:30:00Z', false, 'started 02:59: the end of a night sit'],
  ['2026-09-27', '2026-09-27T17:00:00Z', '2026-09-28T03:59:00Z', true, 'tonight, 11 h in'],
  ['2026-09-27', '2026-09-27T05:00:00Z', '2026-09-27T17:00:00Z', false, 'tonight, 12 h in'],
  ['2026-09-25', '2026-09-27T03:30:00Z', '2026-09-27T05:30:00Z', false, 'two nights ago'],
  // 25 Oct: 03:00 is CET (02:00 UTC); 02:30 comes twice and is never a dawn start.
  ['2026-10-24', '2026-10-24T19:00:00Z', '2026-10-25T04:59:00Z', true, '25 Oct, evening sit, 05:59 CET'],
  ['2026-10-24', '2026-10-24T19:00:00Z', '2026-10-25T05:00:00Z', false, '25 Oct, evening sit, 06:00 CET'],
  ['2026-10-24', '2026-10-25T00:30:00Z', '2026-10-25T06:30:00Z', false, '25 Oct, started 02:30 CEST'],
  ['2026-10-24', '2026-10-25T01:30:00Z', '2026-10-25T06:30:00Z', false, '25 Oct, started 02:30 CET'],
  ['2026-10-24', '2026-10-25T02:00:00Z', '2026-10-25T06:30:00Z', true, '25 Oct, started 03:00 CET'],
  // 29 Mar: 02:00 CET jumps to 03:00 CEST (01:00 UTC).
  ['2026-03-28', '2026-03-29T00:59:00Z', '2026-03-29T05:30:00Z', false, '29 Mar, started 01:59 CET'],
  ['2026-03-28', '2026-03-29T01:00:00Z', '2026-03-29T05:30:00Z', true, '29 Mar, started 03:00 CEST'],
]
for (const [night, started, now, on, what] of sits) assert.equal(startedSitIsOn(night, started, Date.parse(now)), on, what)

console.log(`PASS: the night turns at 06:00 Madrid time on both clock-change mornings (${cases.length} named moments, ${checked} five-minute steps), a copy made before 06:00 is last night's after it, and a sit nobody ended is over at 06:00 unless it is a dawn sit (${sits.length} sits).`)
