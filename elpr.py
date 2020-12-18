#!/usr/bin/python3 -u
# coding=utf8

"""
Popis: Viz. usage()
Autor: Jindrich Vrba
Dne: 21.11.2o2o
Posledni uprava: 17.12.2o2o
"""

#TODO jen bezdratove zakazniky

import sys, getpass, getopt, signal, fcntl, os, rrdtool
sys.path.append('/opt/lib')
import dtb, ssh

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


#TODO doplnit
class Zakaznik:
  """ Trida zakaznika
  """
  def __init__(self, cislo_smlouvy):
    self.cislo_smlouvy = cislo_smlouvy
    #garantovane rychlosti
    self.garant_down = None
    self.garant_up = None
    #aktualni rychlosti
    self.now_down = None
    self.now_up = None
    #nove nastavene rychlosti shapingem
    self.new_down = None
    self.new_up = None
    #statistiky
    self.den_rtt = None
    self.now_stdev = None
    self.now_rtt = None

  #TODO
  def navrhni_shaping(self):
    """ Navrhne vhodnou upravu shapingu.
    """
    print("\nDEBUG %s" % (self))
    print("DEBUG pomer zhorseni rtt %.2f" % (self.now_rtt/self.den_rtt))
    #TODO doladit pomer snizeni
    #TODO nemelo by se brat jeste v potaz max(?15?,self.den_rtt) ?
    snizit=self.now_rtt/self.den_rtt/3
    print("DEBUG pomer znizeni shapingu %.2f" % (snizit))
    self.new_down=int(max(self.garant_down, self.now_down/snizit))
    self.new_up=int(max(self.garant_up, self.now_up/snizit))
    print("DEBUG %s" % (self))

  #TODO
  def proved_shaping(self):
    """ Realizuje shaping.
    """
    #pokud se nic nezmenilo, neni co spoustet
    if (self.now_down==self.new_down and self.now_up==self.new_up):
      return
    print("TODO zmenit rychlost na down:%d, up:%d" % (self.new_down, self.new_up))

    prikaz="""/opt/shaper/add.py change {self.cislo_smlouvy} {self.garant_down} {self.garant_up} {self.new_down} 0 {self.new_up} 0 0 generuj test_vyvoj_eliminace_pretizeni""".format(self=self)
    print("TODO prikaz:%s" % prikaz)

    #errcode = ssh.command("shaper",prikaz)
    #print(errcode)

  def aktualizuj_udaje(self, cursor):
    """ Zapise nove hodnoty do databaze.
    """
    print("DEBUG replace into elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d})".format(self=self))
    cursor.execute("replace into elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d})".format(self=self))

  def __str__(self):
    popis = """objekt zakaznik %d: den_rtt:%s, now_rtt:%s, now_stdev:%s
      """ % (self.cislo_smlouvy, self.den_rtt, self.now_rtt, self.now_stdev)
    popis += """garant_down:%s garant_up:%s now_down:%s now_up:%s
      """ % (self.garant_down, self.garant_up, self.now_down, self.now_up)
    if (self.new_down or self.new_up):
      popis += """new_down:%s new_up:%s
      """ % (self.new_down, self.new_up)
    #return """objekt zakaznik %d: den_rtt:%s, now_rtt:%s, now_stdev:%s
    #garant_down:%d garant_up:%d now_down:%d now_up:%d
    #""" % (self.cislo_smlouvy, self.den_rtt, self.now_rtt, self.now_stdev
    #)
    #return """objekt zakaznik {x.cislo_smlouvy}: den_rtt:{x.den_rtt}, now_rtt:{x.now_rtt}, now_stdev:{x.now_stdev}
    #  garant_down:{x.garant_down} garant_up:{x.garant_up} now_down:{x.now_down} now_up:{x.now_up}""".format(x=self)
    return popis.strip()



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
  upravovat na stovkách routerů co nejblíže k zákazníkovi.

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
  #sys.stderr.write("DEBUG %s: %s\n" % (cislo_smlouvy, rows))
  for ip, in rows:
    #sys.stderr.write("DEBUG %s\n" % ip)
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
      #sys.stderr.write("DEBUG temp: %s\n" % temp)
      if (temp[0] != "-nan"): soucet_down += int(temp[0])
      if (temp[1] != "-nan"): soucet_up   += int(temp[1])

  #print(soucet_down, soucet_up)
  return (soucet_down, soucet_up)


def get_rtt_stdev(cursor,cislo_smlouvy):
  """ Smerodatna odchylka za poslednich 10 minut.
  @param cursor: databazovy kurzor
  @return: smerodatna_odchylka v [ms]
  """
  cursor.execute("select ip_klienta from zakaznici where cislo_smlouvy=%d" % cislo_smlouvy)
  ip_klienta = cursor.fetchone()[0]
  #sys.stderr.write("DEBUG %s: klient %s\n" % (cislo_smlouvy, ip_klienta))

  #zbytek modula 20ti
  zbytek=int(ip_klienta.split('.')[3]) % 20
  #soubory maji misto tecek podtrzitka
  ip_=ip_klienta.replace('.','_')

  if not os.path.isfile("/var/lib/smokeping/Zakaznici/z%s/%s.rrd" % (zbytek,ip_)):
    sys.stderr.write("WARNING IP %s - neexistují RRD statistiky")
    return None

  try:
    stdev=rrdtool.graph('temp.png','-s','now-600s','-e','now',
      'DEF:median=/var/lib/smokeping/Zakaznici/z%s/%s.rrd:median:AVERAGE' % (zbytek,ip_),
      'CDEF:median_ms=median,1000,*',
      'VDEF:stdev=median_ms,STDEV',
      'VDEF:avg_median=median_ms,AVERAGE',
      'PRINT:stdev:%.1lf')[2][0]
  except rrdtool.OperationalError as err:
    sys.stderr.write("WARNING IP %s - rrdtool.OperationalError: %s" % (ip,err))
    return None

  if (stdev=="-nan"):
    return None
  else:
    return float(stdev)


def overit(cursor, cislo_smlouvy):
  """ Overi, jestli dany zakaznik je vhodny k aplikaci rizeneho shapingu.
  TODO
  @param cursor: databazovy kurzor
  @return: (True, Zakaznik) / (False, None)
  """
  #sys.stdout.write("DEBUG %d\n" % (cislo_smlouvy))

  ### TODO pokud je g_u=u a g_d=d nema smysl shapovat - mozna uz v SQL dotazu

  ### pokud zakaznik nevyuziva alespon svoji garantovanou rychlost, neni co shapovat
  down,up=rrd_stat(cursor,cislo_smlouvy)
  #sys.stderr.write("DEBUG poslednich 10m: down=%d, up=%d [kbit]\n" % (down,up))
  #TODO doladit vychozi hodnotu garantovane rychlosti
  cursor.execute("select CAST(greatest(garant_down,max_down/2) AS UNSIGNED),CAST(greatest(garant_up,max_up/2) AS UNSIGNED),max_down,max_up from zakaznici where cislo_smlouvy=%d" % (cislo_smlouvy))
  row=cursor.fetchone()
  #sys.stderr.write("DEBUG sluzba g_d, g_u, d, u [kbit]: %s\n" % str(row))
  g_d, g_u, d, u = row
  sys.stderr.write("DEBUG vyuzito %.2f%% z garant_down\n" % ( 100.0*down/g_d ))
  sys.stderr.write("DEBUG vyuzito %.2f%% z garant_up\n" % ( 100.0*up/g_u ))
  #sys.stderr.write("DEBUG vyuzito %.2f%% z max_down\n" % ( 100.0*down/d ))
  #sys.stderr.write("DEBUG vyuzito %.2f%% z max_up\n" % ( 100.0*up/u ))
  vyuziti_procent_garant=int(max(100.0*down/g_d,100.0*up/g_u))
  #sys.stderr.write("DEBUG vyuziti_procent_garant=%d\n" % vyuziti_procent_garant)
  if (vyuziti_procent_garant<100):
    return (False, None)

  ### odezva by mela kolisat, jinak by se mohlo jednat o false positive kvuli prepojeni zakaznika
  stdev=get_rtt_stdev(cursor,cislo_smlouvy) #v ms
  sys.stderr.write("DEBUG stdev %.1f\n" % stdev)
  #TODO doladit presnou hodnotu
  if (stdev<10):
    return (False, None)

  #pokud proslo vsemi kontrolami, je vhodne k rizenemu shapingu
  z = Zakaznik(cislo_smlouvy)
  z.now_stdev = stdev
  z.garant_down = g_d
  z.garant_up = g_u
  z.now_down = d
  z.now_up = u
  return (True, z)


def get_evidovani_elpr(cursor):
  """ Vrati seznam zakazniku, kteri jsou jiz rizeni pomoci eliminace pretizeni.
  @param cursor: databazovy kurzor
  @return: L
  """
  L = []
  cursor.execute("select cislo_smlouvy,down,up from elpr")
  rows=cursor.fetchall()
  for cislo_smlouvy,down,up in rows:
    z = Zakaznik(cislo_smlouvy)
    z.now_down = down
    z.now_up = up
    L.append(z)

  return L


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
  if not zamek.zamkni():
    sys.stderr.write("Jina instance programu uz je spustena!\n")
    sys.exit(1)

  conn = dtb.connect(charset="utf8", use_unicode=True)
  cursor = conn.cursor()

  #TODO
  #overit(cursor,110328)
  #overit(cursor,)
  #sys.exit()

  #z = Zakaznik(150363)
  #print("DEBUG %s" % (z))
  #z.new_down="test"
  #print("DEBUG %s" % (z))
  #sys.exit()

  #seznam jiz evidovanych
  L_elpr = get_evidovani_elpr(cursor)

  #vycist nove pripady k eliminaci pretizeni
  #TODO zatim zkusebni hodnoty, upravuji jak se mi to hodi pro testovani
  #TODO 10m_rtt je mozna 1h_rtt
  #vycist zakazniky s prekrocenymi meznimi hodnotami, vynechat jiz rizene
  cursor.execute("""
    select Z.cislo_smlouvy,ZS.10m_rtt,ZS.den_rtt
    from zakaznici_statistiky ZS JOIN zakaznici Z ON ZS.cislo_smlouvy=Z.cislo_smlouvy
    where Z.odpojen=0 AND ZS.10m_rtt>5*ZS.den_rtt AND ZS.10m_rtt>15
          AND Z.cislo_smlouvy not in (select cislo_smlouvy from elpr)
    """)
  rows=cursor.fetchall()
  for cislo_smlouvy,rtt_10m,rtt_den in rows:
    sys.stdout.write("DEBUG %10d: 10m_rtt=%d, den:rtt=%d\n" % (cislo_smlouvy,rtt_10m,rtt_den))
    sledovat,zakaznik=overit(cursor,cislo_smlouvy)
    sys.stdout.write("DEBUG === sledovat:%s ===\n\n" % sledovat)
    if (sledovat==True):
      zakaznik.den_rtt = rtt_den
      zakaznik.now_rtt = rtt_10m
      L_elpr.append(zakaznik)

  for zakaznik in L_elpr:
    #print("DEBUG %s" % (zakaznik))
    zakaznik.navrhni_shaping()
    zakaznik.proved_shaping()
    zakaznik.aktualizuj_udaje(cursor)

  conn.close()
