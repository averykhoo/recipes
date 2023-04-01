# Carbonated Fruit

make some fizzy fruit

ingredients:

* dry ice
* wide-mouth polycarbonate bottle (e.g. nalgene)
* some fruit (ideally soft-ish fruit) peeled and maybe sliced open
    * peeled and sliced pears
    * strawberries (safe not to peel these)
    * watermelon chunks
    * peeled grapes
    * orange slices

instructions:

1. peel, slice, and chill the fruit in the fridge
2. put fruit in bottle
3. put one marble sized (diameter 1/2 inch ~= 1.5cm) chunk of dry ice in the bottle
4. cap the bottle
5. wait a bit for the dry ice to turn to gas
6. let the gas infuse into the fruit for a bit
7. very slowly uncap the bottle, letting the gas leak out before fully unscrewing the cap

slightly hand-wavy science:

* a marble has a diameter of about 1/2 inches to 1.5cm -> the volume of dry ice is about 1 to 2 ml (~= 1.5 ml)
* dry ice has a density of 1.6g/cm3 -> the mass of dry ice is 1.6 * 1.5 = 2.4g
* the molar mass of carbon dioxide is about 44 -> we have about 0.054 mols total
* that's about 4e-5 to 8e-5 mols of carbon dioxide (~= 6e-5 mols)
* a nalgene bottle has a volume of about 1.5 liters = 1.5e-3 cubic meters

```python
n = 0.054  # moles of carbon dioxide
R = 8.31  # universal gas constant
T = 298  # room temperature (25 C) converted to kelvin
V = 1.5e-3  # bottle volume of 1.5 liters, converted to cubic meters
P = n * R * T / V
# = (0.054 * 8.31 * 298) / 1.5e-3
# = 89149 pascals
# ~= 90 kPa ~= 0.9 atm
```

* since CO2 is negligible in the atmosphere, we can ignore the fancy partial pressure math and just add 1 atmosphere to
  account for the gas already in the bottle, so the final pressure will be 1.9 atm ~= 28 psi
* doubling size of the chunk (or using a much smaller bottle) would at most double the partial pressure of CO2, bringing
  it up to 2.8 atm ~= 41 psi
* based on [this youtube video](https://www.youtube.com/watch?v=eNTGCgnBoSo), nalgene bottles seem fairly safe up to
  about 40 psi and it shouldn't be *too dangerous* unless you reach 100 psi
* also i've tested this recipe once and excess pressure tends to leak out the cap since you can only tighten it so much
  if you're doing it by hand
* the fruit should be cold (but not frozen) since that lets the gas dissolve into the fruit more easily - the solubility
  of CO2 in water about doubles when you go from 25 to 5 degrees celsius

Solubility of CO2 in pure water at different temperatures ([source](https://www.fao.org/3/ac183e/AC183E06.htm))

| Temperature (°C) | Solubility (mg/litre) |
|------------------|-----------------------|
| 0                | 1.10                  |
| 5                | 0.91                  |
| 10               | 0.76                  |
| 15               | 0.65                  |
| 20               | 0.56                  |
| 25               | 0.48                  |
| 30               | 0.42                  |
| 35               | 0.36                  |
| 40               | 0.31                  |
 	 