#!/usr/bin/python3
# coding=utf8
        
"""
Popis: Viz. usage()
Autor: Jindrich Vrba
Dne: 21.11.2o2o
Posledni uprava: 4.12.2o2o
"""

#TODO jen bezdratove zakazniky

import sys, getpass, getopt, signal, fcntl, os, rrdtool
sys.path.append('./lib')
import dtb

#standardni chovani pri CTRL+C nebo ukonceni roury
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGINT, signal.SIG_DFL)


class Zamek:
  """Zamykani - zajisteni samostatneho pristupu.
  """
  def __init__(self):
    self.lockfile = '/var/lock/elpr'
    self.fl = open(self.lockfile, 'w')
  def zamkni(self):
    try:
      fcntl.lockf(self.fl, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
      return False
    return True


def usage(vystup):
  """ Použití programu
  @param vystup: Kam se bude vypisovat - nejbezneji sys.stderr nebo sys.stdout
  """
  vystup.write("""Detekce a eliminace přetížení rádiových spojů pomocí řízeného shapingu provozu.
(ElPr - Eliminace přetížení)

  V části mojí diplomové práce se budu zabývat detekcí a eliminací
  přetížení rádiových spojů pomocí řízeného shapingu provozu. Představa je
  taková, že to celé bude řídit Linux server, který bude získávat
  informace z desítek páteřních routerů v síti, samotný shaping pak bude
  upravovat na stovkách routerů co nejblíže k zákazníkovi. Jako smart mi
  zde přijde, že je to úplně nový přístup, který by měl reagovat na rychle
  se měnící podmínky v zarušených bezdrátových sítích.
  
Pouziti:
%s ["-h"|"--help"]
  \n""" % sys.argv[0])


def rrd_stat(cursor,cislo_smlouvy):
  """ Statistiky prumernych up a down za poslednich 10 minut.
  @param cursor: databazovy kurzor
  @return: ntice (down, up)
  """
  soucet_down=0
  soucet_up=0

  #TODO IPv6
  #secteme vsechny IP zakaznika
  cursor.execute ("select ip_adresa from lokalni_ip where cislo_smlouvy=%s and aktivni=1" % cislo_smlouvy)
  rows = cursor.fetchall()
  sys.stderr.write("DEBUG %s: %s\n" % (cislo_smlouvy, rows))
  for ip, in rows:
    sys.stderr.write("DEBUG %s\n" % ip)
    if os.path.isfile("/raid/ipac/rrd_real/host-%s.rrd" % ip):
      try:
        temp=rrdtool.graph('temp.png','-s','now-10m','-e','now',
          'DEF:down=/raid/ipac/rrd_real/host-%s.rrd:down:AVERAGE' % ip,
          'CDEF:d_kbit=down,125,/',
          'PRINT:d_kbit:AVERAGE:%.0lf',

          'DEF:up=/raid/ipac/rrd_real/host-%s.rrd:up:AVERAGE' % ip,
          'CDEF:u_kbit=up,125,/',
          'PRINT:u_kbit:AVERAGE:%.0lf',
          )[2]
      except rrdtool.OperationalError as err:
        sys.stderr.write("WARNING IP %s - rrdtool.OperationalError: %s" % (ip,err))
        continue
      sys.stderr.write("DEBUG temp: %s\n" % temp)
      if (temp[0] != "-nan"): soucet_down += int(temp[0])
      if (temp[1] != "-nan"): soucet_up   += int(temp[1])

  #print(soucet_down, soucet_up)
  return (soucet_down, soucet_up)


def overit(cursor, cislo_smlouvy):
  """ Overi, jestli dany zakaznik je vhodny k aplikaci rizeneho shapingu.
  TODO
  @param cursor: databazovy kurzor
  @return: True / False
  """
  sys.stdout.write("DEBUG %d\n" % (cislo_smlouvy))

  #TODO pokud jen g_u=u a g_d=d nema smysl shapovat - mozna uz v SQL dotazu

  #pokud zakaznik nevyuziva alespon svoji garantovanou rychlost, neni co shapovat
  down,up=rrd_stat(cursor,cislo_smlouvy)
  sys.stderr.write("DEBUG down=%d, up=%d [kbit]\n" % (down,up))
  cursor.execute("select CAST(greatest(garant_down,max_down/10) AS UNSIGNED),CAST(greatest(garant_up,max_up/10) AS UNSIGNED),max_down,max_up from zakaznici where cislo_smlouvy=%d" % (cislo_smlouvy))
  row=cursor.fetchone()
  sys.stderr.write("DEBUG g_d, g_u, d, u [kbit]: %s\n" % str(row))
  g_d, g_u, d, u = row
  sys.stderr.write("DEBUG vyuzito %.2f%% z garant_down\n" % ( 100.0*down/g_d ))
  sys.stderr.write("DEBUG vyuzito %.2f%% z garant_up\n" % ( 100.0*up/g_u ))
  sys.stderr.write("DEBUG vyuzito %.2f%% z max_down\n" % ( 100.0*down/d ))
  sys.stderr.write("DEBUG vyuzito %.2f%% z max_up\n" % ( 100.0*up/u ))
  vyuziti_procent_garant=int(max(100.0*down/g_d,100.0*up/g_u))
  sys.stderr.write("DEBUG vyuziti_procent_garant=%d\n" % vyuziti_procent_garant)
  if (vyuziti_procent_garant<100):
    return False

  #TODO doplnit dalsi overeni - napr pingy by mely kolisat, jinak by to mohl byt false positive kvuli prepojeni

  return True


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
  
  zamek = Zamek()

  conn = dtb.connect(charset="utf8", use_unicode=True)
  cursor = conn.cursor()

  #TODO
  overit(cursor,110328)

  if zamek.zamkni():
    #zkusebne, zatim odchytavam jen uplne extremy
    #TODO 10m_rtt je mozna 1h_rtt
    cursor.execute("""
      select Z.cislo_smlouvy,ZS.10m_rtt,ZS.den_rtt
      from zakaznici_statistiky ZS JOIN zakaznici Z ON ZS.cislo_smlouvy=Z.cislo_smlouvy
      where Z.odpojen=0 AND ZS.10m_rtt>8*ZS.den_rtt AND ZS.10m_rtt>20
      """)
    rows=cursor.fetchall()
    for cislo_smlouvy,rtt_10m,rtt_den in rows:
      sys.stdout.write("DEBUG %10d: 10m_rtt=%d, den:rtt=%d\n" % (cislo_smlouvy,rtt_10m,rtt_den))
      sledovat=overit(cursor,cislo_smlouvy)
      sys.stdout.write("DEBUG === sledovat:%s ===\n\n" % sledovat)
  else:
    sys.stderr.write("Jina instance programu uz je spustena!\n")

  conn.close()
