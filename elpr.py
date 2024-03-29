#!/usr/bin/python3 -u
# coding=utf8

"""
Popis: Viz. usage()
Autor: Jindrich Vrba
Dne: 21.11.2o2o
Posledni uprava: 27.4.2o22
"""

import sys, getpass, getopt, signal, fcntl, os, rrdtool
sys.path.append('/opt/lib')
import dtb, ssh

#standardni chovani pri CTRL+C nebo ukonceni roury
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
signal.signal(signal.SIGINT, signal.SIG_DFL)

#minimalni mozna priraditelna rychlost dle specifikace ISP
# - dle CTU VO-S/1/08.2020-9 od 1.1.2021 bezne dostupna rychlost je minimalne 60% inzerovane rychlosti
#                                        minimalni rychlost je minimalne 30% inzerovane rychlosti
#toto nastaveni nema vliv na garantovanou rychlost uzivatele, ktera ma vzdy prednost
#MIN_POMER=0.6 #vychozi hodnota = 60%
MIN_POMER=0.6

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


class Zakaznik:
  """ Trida zakaznika
  """
  def __init__(self, cislo_smlouvy):
    """ Pri vytvoreni objektu zakaznika rovnou naplni parametry sluzby a statistiky.
    """
    self.cislo_smlouvy = cislo_smlouvy

    ### parametry sluzby
    cursor.execute("""
      select garant_down, garant_up, max_down, max_up
      from zakaznici where cislo_smlouvy=%d
      """ % self.cislo_smlouvy)
    row=cursor.fetchone()
    #print("DEBUG %d row: %s" % (self.cislo_smlouvy,str(row)))
    #maximalni rychlosti
    self.max_down = row[2]
    self.max_up = row[3]
    #garantovane rychlosti - z databaze, ale ne nize nez MIN_POMER z max rychlosti
    self.garant_down = max(row[0],int(self.max_down*MIN_POMER))
    self.garant_up   = max(row[1],int(self.max_up*MIN_POMER))
    #aktualni rychlosti, bud jiz evidovane u rizenych zakazniku nebo maximalni rychlosti
    cursor.execute("""
      select down, up
      from elpr where cislo_smlouvy=%d
      """ % self.cislo_smlouvy)
    if (cursor.rowcount!=0):
      row=cursor.fetchone()
      self.now_down = row[0]
      self.now_up   = row[1]
    else:
      self.now_down = self.max_down
      self.now_up   = self.max_up

    ### statistiky
    cursor.execute("""
      select 10m_rtt, den_rtt, tyden_rtt
      from zakaznici_statistiky where cislo_smlouvy=%d
      """ % self.cislo_smlouvy)
    self.now_rtt, self.den_rtt, tyden_rtt = cursor.fetchone()
    if (self.now_rtt==None):
      sys.stderr.write("WARNING zakaznik %d nema statistiky now_rtt\n" % self.cislo_smlouvy)
      #doplnit nejakou potrebnou hodnotu, at muze system postupne opustit
      self.now_rtt=1.0
    #pokud je denni rtt vychylene nebo neni, dosadit pripadne tydenni rtt
    if (self.den_rtt==None):
      self.den_rtt=tyden_rtt
    elif (self.den_rtt>15.0):
      sys.stderr.write("WARNING zakaznik %d extremni denni_rtt=%d (tydenni_rtt=%d)\n"
        % (self.cislo_smlouvy,self.den_rtt,tyden_rtt))
      self.den_rtt=min(self.den_rtt, tyden_rtt)
    #smerodatna odchylka z rrd databaze
    self.now_stdev = get_rtt_stdev(cursor, self.cislo_smlouvy) #v ms
    if (self.now_stdev==None):
      sys.stderr.write("WARNING zakaznik %d nema statistiky now_stdev\n" % self.cislo_smlouvy)
      #doplnit nejakou potrebnou hodnotu, at muze system postupne opustit
      self.now_stdev=0.1

    #vyuziti garantovane rychlosti
    down,up=rrd_stat(cursor,cislo_smlouvy)
    #sys.stderr.write("DEBUG poslednich 10m: down=%d, up=%d [kbit]\n" % (down,up))
    #sys.stderr.write("DEBUG vyuzito %.2f%% z garant_down\n" % ( 100.0*down/self.garant_down ))
    #sys.stderr.write("DEBUG vyuzito %.2f%% z garant_up\n" % ( 100.0*up/self.garant_up ))
    self.vyuziti_procent_garant=int(max(100.0*down/self.garant_down,100.0*up/self.garant_up))
    #sys.stderr.write("DEBUG vyuziti_procent_garant=%d\n" % self.vyuziti_procent_garant)

    ### nove nastavene rychlosti shapingem - o nich se musi teprve rozhodnout
    self.new_down = None
    self.new_up = None


  def over_vhodnost_rizeni(self):
    """ Overi, jestli dany zakaznik je vhodny k aplikaci rizeneho shapingu.
    Urceno pro zakazniky vstupujici do rizeni.
    @return: True / False
    """
    #pokud je g_u=u a g_d=d nema smysl shapovat - mozna uz v SQL dotazu

    #pokud zakaznik nevyuziva alespon svoji garantovanou rychlost, neni co shapovat
    sys.stdout.write("DEBUG vyuzito %d%% garantovane rychlosti\n" % self.vyuziti_procent_garant)
    if (self.vyuziti_procent_garant<100):
      return False

    #odezva by mela kolisat, jinak by se mohlo jednat o false positive kvuli prepojeni zakaznika
    #pripadne jednorazova odchylka v odezve
    sys.stdout.write("DEBUG stdev %.1f\n" % self.now_stdev)
    if (self.now_stdev<6):
      return False

    #pokud proslo vsemi kontrolami, je vhodne k rizenemu shapingu
    return True


  def navrhni_max_rychlosti(self):
    """ Jako nove rychlosti pripravi maximalni rychlosti zakaznika.
    """
    #print("\nDEBUG %s" % (self))
    self.new_down = self.max_down
    self.new_up   = self.max_up
    #print("DEBUG %s" % (self))


  def navrhni_shaping(self):
    """ Navrhne vhodnou upravu shapingu.
    """
    sys.stderr.write("DEBUG vyuziti_procent_garant=%d\n" % self.vyuziti_procent_garant)
    #zakaznik uz neprenasi takove mnozstvi dat, aby melo smysl ridit shaping
    if (self.vyuziti_procent_garant<30):
      self.navrhni_max_rychlosti()
      return

    #print("\nDEBUG %s" % (self))
    pomer_zhorseni=self.now_rtt/self.den_rtt
    print("DEBUG pomer zhorseni rtt %.2f" % (pomer_zhorseni))

    #snizit rychlost
    if (pomer_zhorseni>2.5):
      #nesnizovat o vice nez 40%
      snizit=min(0.4, (pomer_zhorseni/2.5-1)/3)
      print("DEBUG pomer snizeni shapingu -%.2f" % (snizit))
      #snizovani o male procento je zbytecna zatez
      if (snizit<0.05):
        snizit=0.05
      self.new_down=int(max(self.garant_down, self.now_down*(1-snizit)))
      self.new_up=int(max(self.garant_up, self.now_up*(1-snizit)))
    #potrebujeme relativne velke rozmezi, kde rychlost nemenime, kvuli optimalizaci
    elif (1.2<pomer_zhorseni<=2.5):
      self.new_down=self.now_down
      self.new_up=self.now_up
    #zvysit rychlost
    elif (pomer_zhorseni<=1.2):
      #nezvysovat o vice nez 20%
      zvysit=min(0.2,(1/(pomer_zhorseni/1.2)-1)/3)
      print("DEBUG pomer zvyseni shapingu +%.2f" % (zvysit))
      #zvysovani o male procento je zbytecna zatez
      if (zvysit<0.05):
        zvysit=0.0
      self.new_down=int(min(self.max_down, self.now_down*(1+zvysit)))
      self.new_up=int(min(self.max_up, self.now_up*(1+zvysit)))
    else:
      raise RuntimeError("ERROR neni pokryta situace pro pomer_zhorseni %.2f" % (pomer_zhorseni))


  def proved_shaping(self):
    """ Realizuje shaping.
    """
    #pokud se nic nezmenilo, neni co spoustet
    if (self.now_down==self.new_down and self.now_up==self.new_up):
      return

    print("TODO zmenit rychlost na down:%d, up:%d" % (self.new_down, self.new_up))

    prikaz="""/opt/shaper/add.py change {self.cislo_smlouvy} {self.garant_down} {self.garant_up} {self.new_down} 0 {self.new_up} 0 0 web test_vyvoj_eliminace_pretizeni""".format(self=self)
    print("DEBUG prikaz:%s" % prikaz)

    errcode = ssh.command("shaper",prikaz)
    print("DEBUG chybovy kod: %d" % errcode)


  def aktualizuj_udaje(self, cursor):
    """ Zapise nove hodnoty do databaze.
    """
    #pokud se nic nezmenilo, neni co aktualizovat
    if (self.new_down==self.now_down and self.new_up==self.now_up):
      return

    #pokud jsou rychlosti aktualizovany na maximalni rychlosti, prestavame evidovat
    if (self.new_down==self.max_down and self.new_up==self.max_up):
      self.print_vystupni_statistika()
      print("DEBUG delete from elpr where cislo_smlouvy={self.cislo_smlouvy:d}".format(self=self))
      cursor.execute("delete from elpr where cislo_smlouvy={self.cislo_smlouvy:d}".format(self=self))
    else:
      #print("DEBUG replace into elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d})".format(self=self))
      #cursor.execute("replace into elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d})".format(self=self))
      print("INSERT INTO elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d}) ON DUPLICATE KEY UPDATE down={self.new_down:d}, up={self.new_up:d}, uprav=uprav+1".format(self=self))
      cursor.execute("INSERT INTO elpr (cislo_smlouvy, down, up) VALUES ({self.cislo_smlouvy:d}, {self.new_down:d}, {self.new_up:d}) ON DUPLICATE KEY UPDATE down={self.new_down:d}, up={self.new_up:d}, uprav=uprav+1".format(self=self))


  def print_vystupni_statistika(self):
    cursor.execute("select TIMEDIFF(NOW(),vznik),uprav from elpr WHERE cislo_smlouvy=%d" % self.cislo_smlouvy)
    cas,uprav=cursor.fetchone()
    sys.stdout.write("INFO Zakaznik %d opousti rizeni po stravenem case %s a %d upravach rizeni.\n"
       % (self.cislo_smlouvy, cas, uprav))


  def __str__(self):
    popis = """objekt zakaznik %d: den_rtt:%s, now_rtt:%s, now_stdev:%s
      """ % (self.cislo_smlouvy, self.den_rtt, self.now_rtt, self.now_stdev)
    popis += """garant_down:%s garant_up:%s max_down:%s max_up:%s
      """ % (self.garant_down, self.garant_up, self.max_down, self.max_up)
    popis += """now_down:%s now_up:%s""" % (self.now_down, self.now_up)
    if (self.new_down or self.new_up):
      popis += """ -> new_down:%s new_up:%s""" % (self.new_down, self.new_up)
    #return """objekt zakaznik %d: den_rtt:%s, now_rtt:%s, now_stdev:%s
    #garant_down:%d garant_up:%d now_down:%d now_up:%d
    #""" % (self.cislo_smlouvy, self.den_rtt, self.now_rtt, self.now_stdev
    #)
    #return """objekt zakaznik {x.cislo_smlouvy}: den_rtt:{x.den_rtt}, now_rtt:{x.now_rtt}, now_stdev:{x.now_stdev}
    #  garant_down:{x.garant_down} garant_up:{x.garant_up} now_down:{x.now_down} now_up:{x.now_up}""".format(x=self)
    return popis


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
%s <on|off>
%s [-h|--help]

on  ... provadi detekci a eliminaci
off ... kompletne vypne detekci a eliminaci
  \n""" % (sys.argv[0], sys.argv[0]))


def rrd_stat(cursor,cislo_smlouvy):
  """ Statistiky prumernych up a down za poslednich 10 minut.
  @param cursor: databazovy kurzor
  @return: ntice (down, up)
  """
  soucet_down=0
  soucet_up=0

  #secteme vsechny IP zakaznika
  cursor.execute ("select ip_adresa from lokalni_ip where cislo_smlouvy=%s and aktivni=1" % cislo_smlouvy)
  rows = cursor.fetchall()
  #sys.stderr.write("DEBUG %s: %s\n" % (cislo_smlouvy, rows))
  for ip, in rows:
    #sys.stderr.write("DEBUG %s\n" % ip)
    if os.path.isfile("/raid/ipac/rrd_real/host-%s.rrd" % ip):
      try:
        temp=rrdtool.graph('temp.png','-s','now-600s','-e','now',
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


def get_evidovani_elpr(cursor):
  """ Vrati seznam zakazniku, kteri jsou jiz rizeni pomoci eliminace pretizeni.
  @param cursor: databazovy kurzor
  @return: L
  """
  L = []
  cursor.execute("select cislo_smlouvy from elpr")
  rows=cursor.fetchall()
  for cislo_smlouvy, in rows:
    L.append( Zakaznik(cislo_smlouvy) )

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

  if (len(sys.argv) != 2):
    sys.stderr.write("Spatny pocet parametru.\n")
    usage(sys.stderr)
    sys.exit(1)

  if (sys.argv[1] not in ("on","off")):
    sys.stderr.write("Neznamy parametr.\n")
    usage(sys.stderr)
    sys.exit(1)
  operace=sys.argv[1]

  zamek = Zamek()
  if not zamek.zamkni():
    sys.stderr.write("Jina instance programu uz je spustena!\n")
    sys.exit(1)

  conn = dtb.connect(charset="utf8", use_unicode=True)
  cursor = conn.cursor()

  #seznam jiz evidovanych
  L_elpr = get_evidovani_elpr(cursor)

  if (operace=="off"):
    for zakaznik in L_elpr:
      zakaznik.navrhni_max_rychlosti()
      zakaznik.proved_shaping()
      zakaznik.aktualizuj_udaje(cursor)
  else: #operace "on"
    #vycist nove pripady k eliminaci pretizeni
    #vycist zakazniky s prekrocenymi meznimi hodnotami, vynechat jiz rizene
    cursor.execute("""
      select Z.cislo_smlouvy,ZS.10m_rtt,ZS.den_rtt,ZS.tyden_rtt
      from zakaznici_statistiky ZS
        JOIN zakaznici Z ON ZS.cislo_smlouvy=Z.cislo_smlouvy
        left JOIN tarif T ON Z.id_tarifu=T.id
        left JOIN tarif_skupina TS ON T.id_skupina=TS.id
      where Z.odpojen=0 AND Z.max_down!=0
        AND (ZS.10m_rtt>2.5*ZS.den_rtt OR ZS.10m_rtt>2.5*ZS.tyden_rtt) AND ZS.10m_rtt>15
        AND TS.nazev not like "%optika%"
        AND Z.cislo_smlouvy not in (select cislo_smlouvy from elpr)
      """)
    rows=cursor.fetchall()
    for cislo_smlouvy,rtt_10m,rtt_den,rtt_tyden in rows:
      sys.stdout.write("DEBUG %10d: 10m_rtt=%d, den_rtt=%d, tyden_rtt=%d\n" % (cislo_smlouvy,rtt_10m,rtt_den,rtt_tyden))
      zakaznik=Zakaznik(cislo_smlouvy)
      sledovat=zakaznik.over_vhodnost_rizeni()
      sys.stdout.write("DEBUG === sledovat:%s ===\n\n" % sledovat)
      if (sledovat==True):
        L_elpr.append(zakaznik)
      else:
        del zakaznik

    for zakaznik in L_elpr:
      print("\nDEBUG %s" % (zakaznik))
      zakaznik.navrhni_shaping()
      print("DEBUG %s" % (zakaznik))
      zakaznik.proved_shaping()
      zakaznik.aktualizuj_udaje(cursor)

  conn.close()
