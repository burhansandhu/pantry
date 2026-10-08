import test from "node:test";
import assert from "node:assert/strict";
import { splitItems } from "../lib/ingredients.ts";

test("Pasted bullets and quantities become intact ingredient entries", () => {
  assert.deepEqual(splitItems("• 2 chicken breasts\n• 1 can of chickpeas\n• a jar of peanut butter\n• soy sauce, sriracha, and basic spices (salt, pepper, cumin)\n• 1 cup of dry rice"), ["2 chicken breasts", "1 can of chickpeas", "a jar of peanut butter", "soy sauce", "sriracha", "and basic spices (salt, pepper, cumin)", "1 cup of dry rice"]);
});

test("Commas inside notes or quoted entries do not create stray ingredients", () => {
  assert.deepEqual(splitItems('rice (cooked, cooled), "spices, mixed", milk [unsweetened, chilled]'), ["rice (cooked, cooled)", "spices, mixed", "milk [unsweetened, chilled]"]);
});

test("Simple lists, numbered lines, CRLF, deduplication and apostrophes work", () => {
  assert.deepEqual(splitItems("1. cow's milk\r\n2) rice; peas, rice, \n- garlic"), ["cow's milk", "rice", "peas", "garlic"]);
});

test("An empty list stays empty; hyphenated names and decimal amounts survive", () => {
  assert.deepEqual(splitItems(" ,; \r\n"), []);
  assert.deepEqual(splitItems("soy-free sauce, 1.5 cups rice"), ["soy-free sauce", "1.5 cups rice"]);
});
