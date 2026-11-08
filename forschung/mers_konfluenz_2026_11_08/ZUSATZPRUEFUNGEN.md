# Zusaetzliche Ausfuehrungspruefungen

- ADA 4h, beide Richtungen: Konfluenzereignisse des wiederverwendeten
  Forschungsdetektors mit `_plan_one_direction` aus dem Produktionscode
  verglichen. Alle sechs Long- und fuenf Short-Beruehrungen stimmen in
  Kerzenposition, Entry-Limit, Stop und Ziel ueberein.
- ADA-Praefix mit mindestens einem Konfluenzereignis: Anhaengen von
  98 weiteren Kerzen veraendert das bereits bekannte Ereignis nicht.
- Merkmals-Praefixinvarianz, gespiegelte Ausfuehrung und Ausfuehrungsrandfaelle
  stehen in `test_research.py`; Ausfuehrungsprotokoll in `validation.log`.

Diese Stichproben ersetzen keinen allgemeinen Beweis und keine Live-Paritaet
des neuen Hybrids; ein Live-Pfad wurde nicht implementiert.
