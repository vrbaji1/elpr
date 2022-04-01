# Eliminace přetížení (ElPr)
Detekce a eliminace přetížení rádiových spojů pomocí řízeného shapingu provozu.

Eliminaci přetížení řídí Linux server, který získává informace z desítek páteřních routerů v síti,
samotný shaping se pak upravuje na stovkách routerů co nejblíže k zákazníkovi.

## elpr.py
Skript elpr.py detekuje přetížení, navrhuje, nastavuje a průběžně upravuje rychlosti řízeného shapingu.
Ke svojí funkčnosti potřebuje napojení na databázi, na shaping a na RRD databáze.
Skrze napojení na databázi získává informace o tarifu zákazníků a dlouhodobější statistiky datových přenosů.
Pomocí napojení na shaping předává informace o tom, jaké rychlosti je potřeba pro daného zákazníka nastavit.
Statistiky datových přenosů v RRD potřebuje pro zjišťování datových přenosů za poslední dobu.
Napojením na RRD databázi s informacemi o RTT zákazníků získává informace o stavu linky k jednotlivých zákazníkům. Pro tyto účely je možné použít 
například Smokeping, ale je potřeba zajistit aby detekované informace nebyly ovlivňovány samotným shapingem zákazníků, ale detekovaly skutečný stav linky.
Informace o své činnosti zaznamenává do databáze, především údaje o nastavených rychlostech, počátek řízeného shapingu a poslední úpravu. 

```
Použití:
elpr.py <on|off>
elpr.py [-h|--help]

on  ... provádí detekci a eliminaci
off ... kompletně vypne detekci a eliminaci
```

Běžně se však eliminace přetížení spouští pravidelně plánovačem Cron:

```2-57/5  *       * * *   non-root-user time /opt/elpr/elpr.py on```

## stat.py
Skript stat.py slouží k zaznamenávání statistik eliminace pretížení do RRD databáze,
tyto statistiky pak slouží k zobrazení průběhu konfigurace řízeného shapingu v čase v grafech.

```
Použití:
stat.py
stat.py ["-h"|"--help"]
```

I tento skript se spouští pravidelně plánovačem Cron:

```*/2     *       * * *   statistiky /opt/elpr/stat.py```
