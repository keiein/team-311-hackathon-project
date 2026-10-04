// A random whole number from min to max, both included.
// Used by the simulation (SimulationContext.jsx) to pick how many people call in sick (0 to 10)
// or are moved to snow duty (20 to 35) when a disruption is switched on.
//
// Recreated here because the original never reached GitHub: the root .gitignore rule "lib/"
// (from the Python template) hid every folder named lib, including this one.
export function randomIntInclusive(min, max) {
  const low = Math.ceil(min)
  const high = Math.floor(max)
  return Math.floor(Math.random() * (high - low + 1)) + low
}
