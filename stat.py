#!/usr/bin/python3
# coding=utf8

"""
Popis: Viz. usage()
Autor: Jindrich Vrba
Dne: 28.12.2o2o
Posledni uprava:
"""

import sys, getpass, getopt, signal, os, rrdtool
sys.path.append('/opt/lib')
import dtb

#standardni chovani pri CTRL+C nebo ukonceni roury
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGINT, signal.SIG_DFL)


def usage(vystup):
  """ Použití programu
  @param vystup: Kam se bude vypisovat - nejbezneji sys.stderr nebo sys.stdout
  """
  vystup.write("""Statistiky eliminace pretizeni

Zaznamena statistiky eliminace pretizeni do RRD, slouzi k zobrazeni
prubehu konfigurace rizeneho shapingu v case v grafech.

Pouziti:
%s ["-h"|"--help"]
  \n""" % (sys.argv[0]))


def vytvor_rrd(cislo_smlouvy):
  """ Vytvori rrd soubor pro statistiky.
  @param cislo_smlouvy: vytvorit statistiky pro tuto smlouvu zakaznika
  """
  #--step ... predpokladany cas mezi plnenim databaze
  #Data Sources - DS:nazev:typ:max_cas_mezi_updaty:min_hodnota:max_hodnota
  #Round Robin Archive - RRA:vypocet:pomer_neznamych_dat:pocet_zakladnich_jednotek:polozek_v_archivu
  #Archivy: 1 den s presnosti 5 min, 1 tyden s presnosti 15 min, 1 mesic s presnosti 60 min, 1 rok s presnosti 24 hod
  rrdtool.create("/raid/elpr/rrd_real/id-%s.rrd" % cislo_smlouvy,
    "--step","300",
    "DS:down:GAUGE:400:0:U","DS:up:GAUGE:400:0:U",
    "RRA:AVERAGE:0.5:1:288","RRA:AVERAGE:0.5:7:672","RRA:AVERAGE:0.5:31:744","RRA:AVERAGE:0.5:365:365")


def zapsat_statistiky(cursor):
  """ Zaznamenat statistiky do rrd.
  @param cursor: databazovy kurzor
  """
  #nacist statistiky z dtb
  cursor.execute("select cislo_smlouvy, down, up from elpr")
  rows = cursor.fetchall()
  #print(rows)

  #zaznamenat do rrd
  for smlouva,down,up in rows:
    print("DEBUG smlouva %d: d:%d u:%d" % (smlouva,down,up))
    if (not os.path.exists("/raid/elpr/rrd_real/id-%s.rrd" % smlouva)):
      vytvor_rrd(smlouva)
    rrdtool.update("/raid/elpr/rrd_real/id-%s.rrd" % smlouva,
      "-t","down:up",
      "N:%s:%s" % (down, up))


if __name__ == "__main__":
  if (getpass.getuser() != "statistiky"):
    sys.stderr.write("Tento skript smi pouzivat jen uzivatel statistiky.\n")
    sys.exit(1)
  try:
    opts, args = getopt.getopt(sys.argv[1:], "h", ["help"])
  except getopt.GetoptError as err:
    sys.stderr.write("%s\n" % str(err))
    usage(sys.stderr)
    sys.exit(1)
  for o in opts:
    if o[0] in ("-h", "--help"):
      usage(sys.stdout)
      sys.exit()

  if (len(sys.argv) != 1):
    sys.stderr.write("Spatny pocet parametru.\n")
    usage(sys.stderr)
    sys.exit(1)

  conn = dtb.connect(charset="utf8", use_unicode=True)
  cursor = conn.cursor()
  
  zapsat_statistiky(cursor)

  cursor.close()
  conn.close() 
