# Carbonated Fruit

make some fizzy fruit

ingredients:

* dry ice
* wide-mouth polycarbonate bottle (e.g. nalgene)
* some fruit (ideally soft-ish fruit) skinned or at least sliced open
    * pears
    * strawberries
    * watermelon
    * grapes
    * orange slices

instructions:

1. put fruit in bottle
2. put one marble sized (diameter 1/2 inch ~= 1.5cm) chunk of dry ice in the bottle
3. cap the bottle
4. wait a bit for the dry ice to turn to gas

slightly hand-wavy science:

* a marble has a diameter of about 1/2 inches to 1.5cm -> the volume of dry ice is about 1 to 2 ml (~= 1.5 ml)
* dry ice has a density of 1.6g/cm3 -> the mass of dry ice is 1.6 * 1.5 = 2.4g
* the molar mass of carbon dioxide is about 44 -> we have about 0.054 mols total
* that's about 4e-5 to 8e-5 mols of carbon dioxide (~= 6e-5 mols)
* a nalgene bottle has a volume of about 1.5 liters = 1.5e-3 cubic meters

```python
n = 0.054  # moles of carbon dioxide
R = 8.31  # universal gas constant
T = 298  # room temperature converted to kelvin
V = 1.5e-3  # bottle volume of 1.5 liters, converted to cubic meters
P = n * R * T / V
# = (0.054 * 8.31 * 298) / 1.5e-3
# = 89149 pascals
# ~= 90 kPa ~= 0.9 atm
```

since CO2 is negligible in the atmosphere, we can ignore the fancy partial pressure math and just add 1 atmosphere,
hence the final pressure will be ~= 1.9 atm ~= 28 psi

based on [this youtube video](https://www.youtube.com/watch?v=eNTGCgnBoSo), nalgene bottles are fairly safe up to about
40 psi and it shouldn't be *too dangerous* unless you reach 100 psi

