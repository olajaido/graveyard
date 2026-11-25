// Writes content/evidence.generated.json from the held-out result (ui-core UI-LAND-5, design 9).
// Runs before `dev` and `build`. It fails when the file or a field is missing, so the landing page can never show
// a number that is not in eval/heldout/results.v2.json.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
export const SOURCE = resolve(here, '../../eval/heldout/results.v2.json');
export const TARGET = resolve(here, '../content/evidence.generated.json');

function need(value, name) {
  if (value === undefined || value === null) {
    throw new Error(`eval/heldout/results.v2.json has no ${name}`);
  }
  return value;
}

/** The figures the landing page shows, from the parsed result file. Throws on a missing field. */
export function extractEvidence(result) {
  const headline = need(
    result?.heldout?.headline?.dead_precision,
    'heldout.headline.dead_precision',
  );
  const proportion = need(headline.proportion, 'dead_precision.proportion');
  const wilson = need(
    proportion.wilson ?? result?.views?.reviewed?.dead_precision_wilson,
    'the Wilson interval',
  );
  const floors = need(result?.heldout?.floors, 'heldout.floors');
  const evidence = {
    deadPrecision: {
      num: need(proportion.num, 'proportion.num'),
      den: need(proportion.den, 'proportion.den'),
      wilsonLow: need(wilson[0], 'wilson[0]'),
      wilsonHigh: need(wilson[1], 'wilson[1]'),
      passedThreshold: need(headline.passed, 'dead_precision.passed'),
    },
    verdictPassed: need(result?.gate?.passed, 'gate.passed'),
    floorsMet: Object.values(floors).every((floor) => floor?.met === true),
    modelVersion: need(result.model_version, 'model_version'),
    asOf: need(result.as_of, 'as_of'),
  };
  if (
    !Number.isInteger(evidence.deadPrecision.num) ||
    !Number.isInteger(evidence.deadPrecision.den)
  ) {
    throw new Error('the dead precision counts are not integers');
  }
  return evidence;
}

function main() {
  const evidence = extractEvidence(JSON.parse(readFileSync(SOURCE, 'utf8')));
  mkdirSync(dirname(TARGET), { recursive: true });
  writeFileSync(TARGET, `${JSON.stringify(evidence, null, 2)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
