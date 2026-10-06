"""Shot list for the Rituál kontroly animatic: image prompts, on-screen text and sound cues.

Each Shot shows one generated still (or the Veo clip) with a slow camera move. Text kinds:
  action  plain description            line   dialogue, `who` is the speaker
  vo      the son's inner voice        sound  a big sound word (CVAK.)
  heading black card with a slug line  title  black card with the film title
Sound cues are (offset_seconds, effect) or (offset_seconds, effect, gain); effects live in build.py.
"""

from dataclasses import dataclass, field

SON = "tired 33-year-old man with short light-brown hair and stubble in a dark grey sweater"
FATHER = "stern 66-year-old grey-haired man with reading glasses in a dark wool coat"
STYLE = "cinematic 35mm film still, heavy shadows, film grain, photorealistic"
FLUO = "dim sickly yellowish fluorescent office light, muted colors"

IMAGES = {
    # 1-2: office
    "office_wide": f"cramped small company office at dusk, binders and delivery notes on a desk, chipped mug, empty chair, {FLUO}",
    "fluor_tube": "close-up of a flickering fluorescent tube light on an office ceiling, sickly pale yellow glow, dust, dark",
    "desk_items": f"close-up of a cluttered desk, open ring binders, delivery notes, cold coffee in a white mug with a broken handle, {FLUO}",
    "son_desk": f"{SON} hunched over invoices at an office desk, shoulders raised, {FLUO}",
    "son_neck": f"tense neck and raised shoulders of a man in a dark grey sweater seen from behind at a desk, {FLUO}",
    "pen_hover": f"extreme close-up of a man's hand holding a pen frozen just above a paper invoice, {FLUO}",
    "corridor_feet": "low angle close-up of an old man's heavy leather shoes walking on worn linoleum in a dim office corridor",
    "door_opens": "office door opening, silhouette of an old man standing in the doorway backlit by corridor light, dark office",
    "father_doorway": f"{FATHER} standing in an office doorway, disappointed pitying look, {FLUO}",
    "father_nose": f"close-up of {FATHER} rubbing the bridge of his nose with two fingers, eyes closed",
    "son_eyes": f"extreme close-up of the anxious wide eyes of a {SON}, {FLUO}",
    "gate_lock": "close-up of a man's hand on the metal handle of a warehouse gate, padlock, late afternoon sunlight, vivid colors",
    "son_looks_down": f"{SON} looking down at the desk ashamed like a little boy, {FLUO}",
    "father_turns": f"{FATHER} turning away in an office doorway seen from behind, waving his hand dismissively",
    "door_closed": f"closed office door seen from inside, linoleum floor, {FLUO}",
    "son_half_standing": f"{SON} frozen half standing up from an office chair, palms on the desk, {FLUO}",
    "son_still_face": f"close-up of a {SON}, motionless face, pulsing vein on his neck, sweat, {FLUO}",
    "montage_letter": "close-up of an official envelope with a red stamp on a dark table, ominous low light",
    "montage_bank": "close-up of a printed bank statement on a dark table, red numbers, moody low light",
    "montage_father_alone": "lonely old grey-haired man sitting alone at a kitchen table with one plate and one spoon, old wall clock, dim lamp",
    "montage_notary": "empty notary office, large wooden desk with documents and a fountain pen, cold light",
    "son_mug_grip": f"extreme close-up of a hand gripping a white mug with a broken handle, white knuckles, {FLUO}",
    "silence_office": "small office flooded with soft bright daylight, window wide open, a paper lifted by the wind, empty, peaceful",
    "son_breath": f"{SON} with eyes closed taking a deep breath, soft daylight on his face, peaceful",
    "son_face_hands": f"{SON} hiding his face in his hands at an office desk, despair, {FLUO}",
    # 3: the leaving ritual
    "son_jacket": f"{SON} zipping up a dark jacket in an office, keys with a red plastic tag in his hand, {FLUO}",
    "corridor_lamp": "dim office corridor in the evening, a half-open door at the far end with warm desk lamp light inside",
    "father_desk": f"{FATHER} sitting at a desk turning pages of documents, warm desk lamp, dark office",
    "glasses_case": "close-up of old wrinkled hands folding reading glasses into a glasses case on a desk, warm lamp light",
    "son_waiting": f"{SON} sitting on the edge of an office chair wearing a zipped jacket, waiting, {FLUO}",
    "father_coat_keys": f"{FATHER} in an unbuttoned coat standing in an office doorway, a bunch of keys in his hand",
    "wet_mug": f"a wet white mug with a broken handle next to a small office sink, {FLUO}",
    "father_smile": f"{FATHER} with his coat buttoned up, faint almost kind smile, car keys in hand, in a doorway",
    "light_switch": "close-up of an old finger pressing a light switch on a wall in a dark corridor",
    "warehouse_light": "heavy warehouse door with light switching on inside, shelves of boxes, dark corridor",
    "father_folder": f"{FATHER} holding a thick folder under his arm in an office doorway, sighing",
    "father_in_chair": f"{FATHER} sitting in an office chair reading delivery notes from an open desk drawer, {FLUO}",
    "son_standing_jacket": f"{SON} standing in a zipped jacket in an office like a visitor, hands at his sides, {FLUO}",
    "papers_wrong": f"close-up of delivery notes put back into a desk drawer out of order, one sheet sticking out, {FLUO}",
    "father_hurt": f"close-up of a {FATHER}, quietly offended, almost hurt expression",
    "son_eye_contact": f"{SON} in a jacket turning in a doorway and looking straight into the camera, lips parted, {FLUO}",
    # 4: car park
    "car_inside": "inside a car at dusk, a man's hands on the steering wheel, dashboard glow, engine running",
    "rearview": "car rear-view mirror at dusk reflecting a small company building with one lit window",
    "silhouette_blinds": "lit office window at night seen from outside, silhouette of an old man moving behind the blinds",
    # 5: kitchen, the hour at a distance
    "kitchen_dark": "dark old-fashioned kitchen at night lit only by a small yellow light above the cooker hood, crocheted doily, vase",
    "shoes_wall": "pair of black leather men's shoes standing neatly side by side against a wall on a hallway floor, dim light",
    "son_kitchen": f"{SON} sitting at a kitchen table in a jacket in the dark, phone in front of him, dim yellow light",
    "phone_table": "smartphone lying face up on a kitchen table, black screen, dim yellow light",
    "headlights_ceiling": "looking up at a dark kitchen ceiling at night, bright streaks of headlight light sweeping across the ceiling and wall, no cars",
    "father_dark_office": f"{FATHER} sitting in a dark office lit only by the blue glow of a computer monitor, opening a drawer",
    "mug_trash": "white mug with a broken handle lying in an office trash bin, blue monitor light, dark",
    "cabinet_bottle": "bottle of cheap whisky hidden behind a cereal box in a kitchen cabinet, dim light",
    "pour_glass": "close-up of whisky being poured into a wide tumbler on a kitchen table, dim yellow light",
    "shoulders_drop": f"{SON} seen from behind at a kitchen table, a tumbler of whisky, dim yellow light",
    "hide_glass": "man's hand quickly hiding a whisky glass in a kitchen cabinet behind a cereal box, motion blur",
    "rinse_mouth": "man rinsing his mouth at a kitchen tap at night, dim light",
    "son_interrogation": f"{SON} sitting stiff at a kitchen table with hands flat on the table, dim light",
    # 6: the half-hour round
    "front_door_key": "close-up of a key turning in a front door lock from inside, dark hallway, warm dim light",
    "front_door_handle": "close-up of an old man's hand pressing down the handle of a front door, dark hallway",
    "slippers": "close-up of an old man's feet in slippers walking slowly on a laminate floor in a dark house",
    "window_handle": "close-up of an old hand turning a white window handle at night, dark living room",
    "terrace_door": "close-up of an old hand holding down the handle of a glass terrace door at night",
    "son_fingers": "close-up of a man's tense spread fingers on a kitchen table, dim yellow light",
    "father_kitchen": f"{FATHER} standing by the stove in a dark kitchen, dim yellow light",
    "stove_knobs": "close-up of an old hand turning stove knobs one by one, dim kitchen light",
    "wet_finger": "close-up of an old man's wet fingertip after touching the edge of a kitchen sink, dim light",
    "father_look": f"{FATHER} giving a cold side glance, corner of his mouth slightly raised, dim kitchen light",
    "back_door_handle": "close-up of an old hand slowly pressing a back door handle in a kitchen at night",
    "son_shoulders_up": f"{SON} at a kitchen table with shoulders raised to his ears, tense, dim light",
    "stairs_glass": f"{SON} stopping on dark stairs holding a whisky glass and a bottle, listening",
    "garage_door": "metal garage door in a dark basement shaken by an old man's hand, bare bulb",
    # 7: the son's room
    "attic_room": "small attic bedroom at night, single bed, wardrobe, desk with a laptop, sloped ceiling, dim lamp",
    "key_turn_inside": "close-up of a man's hand slowly turning a key in a bedroom door from inside, dark",
    "son_bed_glass": f"{SON} sitting on the edge of a bed holding a whisky glass with both hands, dark attic room, dim lamp",
    "hallway_window": "dark house hallway at night, an old hand on a window handle",
    "stairs_dark": "dark wooden staircase at night seen from above, an old man's shadow climbing",
    "door_gap": "gap under a bedroom door at night, shadow of two feet standing outside, seen from inside the dark room",
    "handle_inside": "close-up of a bedroom door handle seen from inside a dark room, being pressed down from outside",
    "father_hall_face": f"close-up of a {FATHER} in a dark hallway, calm satisfied face, hand on a door handle",
    "son_jaw": "extreme close-up of a clenched jaw and tense neck muscles of a stubbled man, dark room",
    "son_chest": "close-up of a man's chest in a dark grey sweater, tense, holding his breath, dark room",
    "knuckles_glass": "extreme close-up of white knuckles gripping a whisky tumbler, dark room, dim lamp",
    "father_walks_away": "old grey-haired man in slippers walking away down a dark hallway, seen from behind",
    "son_body_map": f"{SON} sitting rigid on a bed, jaw clenched, staring, dark attic room",
    "son_drinks": f"{SON} drinking from a whisky tumbler with eyes closed in a dark attic room",
    "bottle_level": "half-empty whisky bottle and a tumbler on a bedside table, dark room, dim lamp",
    # 8-9: night and morning
    "son_bed_night": f"{SON} lying dressed on a bed in the dark with eyes open staring at the ceiling, faint moonlight",
    "empty_glass": "empty tumbler with a brown ring at the bottom on a bedside table at night, moonlight",
    "morning_kitchen": f"{FATHER} clean-shaven in a clean white shirt reading a newspaper with coffee, grey morning kitchen light",
    "shaking_hand_coffee": "close-up of a trembling hand stirring coffee in a cup with a spoon, grey morning light",
    "father_newspaper": f"{FATHER} not looking up from his newspaper at a kitchen table, grey morning light",
    "son_morning": f"{SON} looking down into a coffee cup, ashamed, grey morning light",
    "father_keys_morning": f"{FATHER} standing up from a kitchen table picking up car keys, grey morning light",
    "father_sits_again": f"{FATHER} sitting back down at a kitchen table opening a newspaper, grey morning light",
    "son_looks_at_father": f"{SON} staring numbly across a kitchen table, grey morning light",
}
IMAGES = {key: f"{prompt}, {STYLE}" for key, prompt in IMAGES.items()}

VEO_CLIP = "ritual_kontroly.mp4"  # the 4 s Veo master shot, played at half speed in scene 7


@dataclass
class Shot:
    img: str | None = None  # IMAGES key, VEO_CLIP, or None for a black card
    text: str = ""
    kind: str = "action"
    who: str = ""
    dur: float | None = None  # None: long enough to read the text
    move: str = ""  # in | out | left | right | still; empty picks one
    sfx: list = field(default_factory=list)
    bed: str | None = None  # ambience; None keeps the previous one
    clock: str = ""
    fx: str = ""  # blur | bright | vivid | sweep (headlights crossing the frame)


SHOTS: list[Shot] = []


def add(img, text="", kind="action", **kw):
    SHOTS.append(Shot(img, text, kind, **kw))


def line(img, who, text, **kw):
    add(img, text, "line", who=who, **kw)


def vo(img, text, **kw):
    add(img, text, "vo", **kw)


def heading(text, bed, dur=3.2):
    add(None, text, "heading", bed=bed, dur=dur)


def card(text, dur=2.0):
    add(None, text, "heading", dur=dur)


STEPS = [(0.2, "step_r"), (0.75, "step_l"), (1.3, "step_r"), (1.85, "step_l"), (2.4, "step_r")]

# --- Title --------------------------------------------------------------------------------------
add(None, "RITUÁL KONTROLY\nSekvencia 1: Zlomená pamäť a tiché stroje", "title", dur=7, bed="hum")

# --- 1. Office ----------------------------------------------------------------------------------
heading("1. INT. KANCELÁRIA FIRMY — PODVEČER", "office")
add("office_wide", dur=4.5, clock="17:46", move="in")
add("fluor_tube", "Svetlo žiarivky má ten lacný, bzučiaci žltkastý odtieň, z ktorého po šiestich hodinách bolia oči.",
    sfx=[(1.8, "flicker")])
add("desk_items", "Tri otvorené šanóny. Dodacie listy z ranného rozvozu. Napoly studená káva v hrnčeku s odbitým uchom.")
add("son_desk", "Má 33 rokov, ale v svaloch na krku nosí váhu sedemdesiatnika.")
add("son_neck", "Ramená vytiahnuté k ušiam, akoby celý deň čakal úder zozadu.")
add("corridor_feet", "KROKY.", "sound", dur=3.2, sfx=STEPS)
add("pen_hover", "Syn prestane písať. Pero zostane visieť milimeter nad papierom.",
    sfx=[(0.3, "step_r", 0.8), (0.9, "step_l", 0.8), (1.5, "step_r", 0.8)])
vo("corridor_feet", "Pravá päta dopadá tvrdšie. Zastal pri dverách skladu. Dve sekundy. Tri.", move="left",
   sfx=[(0.3, "step_r"), (0.9, "step_l")])
vo("pen_hover", "Teraz ide ďalej — pomalšie. To nie je únava. To je hľadanie.", move="still",
   sfx=[(0.6, "step_r", 0.9), (1.6, "step_l", 0.9), (2.6, "step_r", 0.9)])
add("son_neck", "Za tie roky sa naučil čítať kroky na linoleu ako seizmograf.")
add("door_opens", "Dvere sa otvoria bez zaklopania.", sfx=[(0.2, "door_open")])
add("father_doorway", "Otec nevstúpi s krikom. Vstúpi s hlbokým, unaveným povzdychom človeka, ktorý nesie kríž za celú rodinu.",
    sfx=[(0.6, "sigh")])
add("son_desk", "Synovi sa stiahne žalúdok. Prestane dýchať.", move="in")
line("father_doorway", "OTEC (ticho)", "Zase si nezavrel bránu na sklade.")
add("father_nose", "Otec si dvoma prstami pretrie koreň nosa.")
line("father_doorway", "OTEC", "Idem okolo a hlavná brána dokorán. Každý odtiaľ môže odniesť tovar za tisíce eur.")
line("father_nose", "OTEC (ešte tichšie)", "Chceš ma zničiť? Chceš, aby sme skrachovali?")
add("son_eyes", "V hlave sa mu v tej sekunde spustí blesková vojna.", sfx=[(0.2, "heartbeat")])
add("gate_lock", "CVAK.", "sound", dur=2.6, fx="vivid", bed="gate", sfx=[(0.7, "cvak", 1.2)])
vo("gate_lock", "Zavrel si ju. Počul si ten zámok. Potiahol si za kľučku, aby si to skontroloval.", fx="vivid")
add("father_doorway", "Otcov hlas je však taký istý, taký pokojný vo svojej neochvejnej pravde…", bed="office")
add("gate_lock", "Zámok zapadá — ale CVAK nepočuť.", fx="blur", bed="muffled", move="out")
vo("son_eyes", "A čo ak si predsa len zabudol? Čo ak si naozaj taký neschopný?", bed="office")
vo("son_desk", "Veď pred tromi rokmi si pokazil tú faktúru… spomeň si, vtedy si mal aj tie dlhy… všetko si vtedy posral…")
vo("son_looks_down", "On má pravdu. Strácaš hlavu.")
line("son_looks_down", "SYN", "Prepáč, otec.", move="still")
add("son_looks_down", "Jeho hlas znie cudzo — ako hlas malého chlapca, nie muža, ktorý túto prevádzku denne sám ťahá od rána do večera.")
line("son_half_standing", "SYN", "Idem to skontrolovať.", sfx=[(0.3, "chair")])
line("father_turns", "OTEC (mávne rukou)", "Netreba.")
line("father_turns", "OTEC", "Už som to urobil za teba. Ako vždy.", move="still")
line("father_turns", "OTEC", "Neviem, čo s tebou bude, keď tu raz nebudem. Nič neudržíš v hlave.", move="in")
add("door_closed", "CVAK.", "sound", dur=2.4, sfx=[(0.3, "door_close")])
add("son_half_standing", "Zostane zamrznutý v polovici pohybu — nie celkom sediac, nie celkom stojac.", move="still")

# --- 2. Office, continued --------------------------------------------------------------------------
heading("2. INT. KANCELÁRIA — POKRAČOVANIE", "office")
add("office_wide", "Zostal sám. Ticho. Iba žiarivka.", clock="17:49", move="out")
add("son_still_face", "A vtedy to príde.", bed="pulse")
add("son_still_face", "Ten hnev. Nie hnev, ktorý núti búchať do stola. Hustý, čierny, nezastaviteľný príval tekutého jedu, "
    "ktorý mu stúpa od žalúdka až do hrdla.", move="in")
add("montage_letter", dur=1.4, move="in")
add("montage_bank", dur=1.4, move="in")
add("montage_notary", "Strach, že ho vydedí a zostane na ulici bez eura.")
add("montage_father_alone", "A tá strašná, dusivá ľútosť: otec je starý, rozvedený a sám.")
vo("montage_father_alone", "A ty ho tu predsa nemôžeš nechať zomrieť v tej jeho samote.", move="still")
add("son_mug_grip", "Prsty sa zovrú okolo hrnčeka. Tak pevne, až mu zbelejú kĺby.")
add("silence_office", dur=3.5, fx="bright", bed="silence_day", move="in")
add("son_breath", dur=4.5, fx="bright", sfx=[(0.4, "breath")], move="in")
add("silence_office", "Svet, v ktorom ten starý chlap už nedýcha — a jeho konečne nikto netrestá za to, že vôbec existuje.",
    fx="bright", move="right")
add("son_still_face", dur=1.2, bed="office", sfx=[(0.0, "hum_hit")], move="still")
vo("son_still_face", "Panebože. Ja som monštrum. Želám vlastnému otcovi smrť.", move="in")
vo("son_face_hands", "On mi dal prácu. Dal mi bývanie. A ja som takýto nevďačník.")
add("son_face_hands", "Ten spravodlivý hnev, ktorý mal patriť otcovi, znova zatlačí hlboko do seba. Proti vlastnému telu — ako vždy.",
    move="still")
add("son_neck", "Hruď sa stiahne. Ramená stuhnú.")
add("son_face_hands", "V tichu kancelárie nesie vinu za hriech, ktorý spáchal otec na ňom.", move="out", dur=6)

# --- 3. The leaving ritual -------------------------------------------------------------------------
heading("3. RITUÁL „ODCHÁDZAM“", "office_evening")
add("son_jacket", "Zatvorí posledný šanón. Oblečie si bundu. Zoberie kľúče s červeným štítkom SKLAD.", clock="18:12",
    sfx=[(1.0, "keys")])
add("corridor_lamp", dur=3, sfx=[(0.2, "step_soft"), (0.8, "step_soft"), (1.4, "step_soft"), (2.0, "step_soft")])
add("father_desk", "Otec listuje v papieroch. Lenže nepracuje. Už tretíkrát otočí tú istú stranu.", sfx=[(1.5, "page")])
line("father_desk", "SYN", "Idem domov.", move="still")
add("father_desk", "Otec nezdvihne hlavu. Pauza — dlhá presne toľko, aby to zabolelo.", move="in")
card("ODCHOD Č. 1")
line("glasses_case", "OTEC (takmer prívetivo)", "Dobre. Idem aj ja.", clock="18:14")
line("glasses_case", "SYN", "Zapnem alarm, keď budeme odchádzať.", move="still")
line("father_desk", "OTEC", "Choď si po veci. Idem hneď za tebou.")
add("son_waiting", "Sadne si na kraj stoličky. V bunde, zips až pod bradu. Čaká.")
add("corridor_lamp", "Otcove kroky nesmerujú k východu. Smerujú ku skladu.",
    sfx=[(0.3, "step_r", 0.6), (0.9, "step_l", 0.5), (1.5, "step_r", 0.4), (2.1, "step_l", 0.3)])
vo("son_waiting", "Jeden.", dur=2.5, move="still")
card("ODCHOD Č. 2")
line("father_coat_keys", "OTEC", "Tak. Idem.", clock="18:21", sfx=[(0.3, "keys")])
line("son_waiting", "SYN", "Dobre.", sfx=[(0.2, "chair")])
line("wet_mug", "OTEC", "To tu necháš len tak? Mal by si to vyhodiť. Všetko tu u teba vyzerá ako po vojne.")
add("corridor_lamp", "Otočí sa a odíde. Nie k východu. Do svojej kancelárie.",
    sfx=[(0.3, "step_r", 0.6), (0.9, "step_l", 0.5), (1.5, "step_r", 0.4)])
vo("son_waiting", "Dva.", dur=2.5, move="still")
card("ODCHOD Č. 3")
line("father_smile", "OTEC", "Ešte pozriem poštu a idem. Ty choď, nečakaj na mňa.", clock="18:33")
line("son_waiting", "SYN", "Počkám. Zapnem alarm.")
line("father_smile", "OTEC (jemne sa usmeje)", "Ty a alarm.", move="in")
vo("son_waiting", "Tri. Neodíde. Vieš, že neodíde. Tak prečo tu sedíš v bunde ako idiot?")
card("ODCHOD Č. 4")
add("light_switch", "CVAK.", "sound", dur=2.4, clock="18:41", sfx=[(0.5, "switch")])
add("son_standing_jacket", "Synovi poskočí srdce. Vstane. Konečne.", sfx=[(0.2, "heartbeat"), (1.2, "chair")])
add("corridor_lamp", "K východu je to jedenásť krokov. Kroky sa zastavia po štyroch. Otočia sa.",
    sfx=[(0.2, "step_r"), (0.75, "step_l"), (1.3, "step_r"), (1.85, "step_l"), (3.2, "step_r", 0.7), (3.8, "step_l", 0.6)])
add("warehouse_light", "CVAK.", "sound", dur=2.6, sfx=[(0.1, "door_open", 0.7), (1.2, "switch")])
line("father_folder", "OTEC (povzdych)", "Toto tam leží od pondelka. Nikto sa na to ani nepozrie. Pozriem to ja a idem.")
vo("son_standing_jacket", "Štyri. Zhasol si len preto, aby si mohol znova rozsvietiť. Aby som vstal. Aby si videl, ako vstávam.")
card("ODCHOD Č. 5")
add("father_in_chair", "Otec si sadne na synovu stoličku. Na jeho miesto. Mimochodom vytiahne zásuvku.", clock="18:52",
    sfx=[(0.4, "chair"), (2.0, "drawer")])
line("father_in_chair", "OTEC", "Ja už fakt idem. Len sa pozriem, čo tu máš.", move="still", sfx=[(1.0, "page")])
line("son_standing_jacket", "SYN (potichu)", "To sú ranné dodacie. Všetko sedí.")
line("father_in_chair", "OTEC (nezdvihne zrak)", "Uvidíme.", move="in", sfx=[(0.8, "page")])
vo("son_standing_jacket", "Päť. Toto je tvoje územie. Tvoj stôl. Tvoja zásuvka. Nič z toho nie je tvoje.")
card("ODCHOD Č. 6")
add("papers_wrong", "Papiere vráti do zásuvky. Nie celkom tak, ako boli. Syn si to všimne. Otec vie, že si to syn všimne.",
    clock="19:03", sfx=[(0.8, "drawer")])
line("father_coat_keys", "OTEC", "Tak. Teraz už naozaj idem.", sfx=[(0.4, "keys")])
line("son_standing_jacket", "SYN", "Tak poďme.")
line("father_hurt", "OTEC", "Choď ty. Ja tu ešte niečo dorobím.")
line("father_hurt", "OTEC", "Niekto musí.", move="still")
line("son_eye_contact", "SYN", "Povedal si, že ideš.")
line("father_hurt", "OTEC (dotknuto)", "Veď idem. O chvíľu. Čo ma naháňaš?", move="in")
line("father_hurt", "OTEC", "Už aj tu ma budeš kontrolovať?", move="still")
add("son_eye_contact", "Kontrolór obvinil kontrolovaného z kontroly. Tých šesť „idem“ sa zrúti do jedného nemého výkriku, "
    "ktorý nemá kam ísť.", move="in")
line("son_eye_contact", "SYN", "…Dobrú noc.", move="still")
add("corridor_lamp", "Alarm nezapne. Nemôže — otec je vnútri.", sfx=[(0.2, "step_soft"), (0.8, "step_soft"), (2.4, "door_close", 0.6)])

# --- 4. Car park ---------------------------------------------------------------------------------
heading("4. EXT. PARKOVISKO PRED FIRMOU — SÚMRAK", "car")
add("car_inside", "Motor beží. Ruky na volante — na desiatej a druhej, ako v autoškole.", clock="19:05")
add("rearview", "V spätnom zrkadle: okno jeho kancelárie je tmavé.")
add("rearview", "Potom sa rozsvieti.", move="in", sfx=[(0.4, "switch", 0.25)])
add("silhouette_blinds", "Za žalúziami sa pohne silueta. Pomaly. Bez zhonu. Ako niekto, kto má na všetko celý večer.")
vo("silhouette_blinds", "Teraz je tam sám. V tvojej zásuvke. V tvojom počítači. Zajtra ráno niečo nájde. Vždy niečo nájde.",
   move="in")
vo("car_inside", "A keď nenájde nič, nájde bránu, ktorú si „nechal otvorenú“.")
add("car_inside", "Mohol by sa vrátiť. Zaradí jednotku a odíde.", move="still", sfx=[(1.6, "car_leave")])
add("rearview", "V spätnom zrkadle jeho okno svieti ďalej.", move="out", bed="black_soft")

# --- 5. Kitchen, the hour at a distance ----------------------------------------------------------
heading("5. INT. OTCOV DOM — KUCHYŇA — HODINA NA DIAĽKU", "kitchen")
add("kitchen_dark", "Dom je otcov. Vidno to na všetkom.", clock="19:21")
add("shoes_wall", "Ani po rokoch si nevie vyzuť topánky bez toho, aby ich zarovnal k stene.")
add("son_kitchen", "Hlavné svetlo nezapne. Bundu si nevyzlečie.")
add("phone_table", "Mobil displejom nahor. Nič. Otec nenapíše. Nikdy nepíše. Ticho je súčasťou rituálu.")
add("headlights_ceiling", dur=4.5, clock="19:34", sfx=[(0.0, "car_pass")], move="right", fx="sweep")
add("son_kitchen", "Telo sa trhne — celé, naraz. Nie je to otcovo auto. Otcov diesel znie inak.", sfx=[(0.1, "chair", 0.6)])
vo("son_kitchen", "Si doma. Si dospelý chlap a si doma. Nikto ťa tu nevidí.", move="in")
add("son_kitchen", "Telo mu neverí.", dur=3, move="still")
add("father_dark_office", "Tou istou chvíľou vo firme: otec na synovej stoličke. Nič konkrétne nehľadá.", bed="office_night",
    sfx=[(1.5, "drawer", 0.7)])
add("mug_trash", "Či je to skutočnosť, alebo synova predstava, film nerozhodne.", sfx=[(0.3, "bin")])
add("kitchen_dark", dur=3, clock="19:52", bed="kitchen", move="out")
add("cabinet_bottle", "Za krabicou s cereáliami stojí fľaša lacnej whisky.", sfx=[(0.2, "cabinet")])
add("pour_glass", "Nie veľa. Na dva prsty.", sfx=[(0.3, "pour")])
add("shoulders_drop", "Prejde minúta. Dve. Ramená klesnú o centimeter. Je to prvý centimeter za celý deň.", move="out")
add("shoulders_drop", "Hučanie v hlave stíchne o pol tónu.", move="still", bed="kitchen_soft")
add("headlights_ceiling", "Ďalšie svetlá. Pohár narazí o stôl. Nie je to on.", clock="20:08",
    sfx=[(0.0, "car_pass"), (0.9, "glass_table")], bed="kitchen", fx="sweep")
add("headlights_ceiling", "Svetlá na strope. Tentoraz pomalé. Hlboký zvuk dieselu.", clock="20:20", dur=6, move="left",
    sfx=[(0.0, "diesel")], fx="sweep")
add("son_kitchen", "Tentoraz je to on. Hodinu a štvrť po synovi.", move="in")
add("hide_glass", "Pohár do skrinky, za cereálie.", dur=2.8, sfx=[(0.0, "chair"), (0.9, "cabinet")])
add("rinse_mouth", "Tridsaťtriročný muž skrýva pohár ako štrnásťročný chlapec.", sfx=[(0.1, "tap")])
add("son_interrogation", "Ruky položí na stôl. Ako na výsluchu.", move="in")

# --- 6. The half-hour round --------------------------------------------------------------------------
heading("6. POLHODINOVÁ OBCHÔDZKA", "house")
add("front_door_key", dur=3.2, clock="20:21", sfx=[(0.3, "door_close", 0.7), (1.2, "key_turn"), (2.1, "key_turn")])
add("front_door_handle", "CVAK.", "sound", dur=2.6, sfx=[(0.4, "handle")])
add("front_door_handle", "CVAK. CVAK.", "sound", dur=2.6, move="still", sfx=[(0.3, "handle"), (1.0, "handle")])
add("front_door_handle", "Otec stláča kľučku dverí, ktoré sám pred sekundou zamkol.", move="out")
add("son_interrogation", "Nepozdraví. Nezavolá. Obaja vedia, že syn sedí v kuchyni a počúva.")
add("slippers", "Otec nechodí potichu preto, aby syna nerušil. Chodí potichu preto, aby ho syn musel počúvať.",
    sfx=[(t, "shuffle") for t in (0.2, 1.0, 1.8, 2.6, 3.4, 4.2)])
add("window_handle", dur=4, clock="20:22", sfx=[(0.4, "window_open"), (2.6, "cvak")])
add("window_handle", "Otec otvoril zatvorené okno, aby skontroloval, či je zatvorené.", move="still")
add("terrace_door", "Kľučka zostane stlačená. Tri sekundy.", clock="20:24", dur=4.5, sfx=[(0.3, "handle"), (3.6, "cvak")])
add("son_fingers", dur=2.5, sfx=[(0.5, "heartbeat")])
add("father_kitchen", "Otec vojde do kuchyne. Na syna sa nepozrie.", clock="20:26", sfx=[(0.2, "shuffle"), (1.0, "shuffle")])
add("stove_knobs", "Tik. Tik. Tik. Tik.", "sound", dur=3.6, sfx=[(t, "tick") for t in (0.5, 1.1, 1.7, 2.3)])
add("stove_knobs", "Všetky sú vypnuté. Aj tak každý otočí na nulu.", move="still")
add("wet_finger", "Prejde prstom po hrane drezu. Je mokrá.")
add("father_look", "Potom — prvýkrát — sa pozrie na syna. Kútik úst sa mu pohne. Nie je to úsmev.", move="in")
line("father_look", "OTEC", "Hm.", dur=2.5, move="still")
line("father_kitchen", "OTEC (ľahostajne)", "Zamykal si?")
line("son_interrogation", "SYN", "Áno.", dur=2.5, move="still")
add("back_door_handle", "CVAK.", "sound", dur=4.8, sfx=[(0.3, "handle"), (3.6, "cvak")])
add("son_shoulders_up", "Ramená, ktoré whisky spustila o centimeter, znova vyletia k ušiam.")
add("father_look", "Otec spomalí. Nie preto, že by niečo hľadal. Spomalí, pretože to vidí. Na tvári sa mu niečo uvoľní. Nasýtenie.",
    move="in")
line("father_look", "OTEC", "Hm.", dur=2.5, move="still", sfx=[(1.2, "shuffle"), (1.9, "shuffle")])
add("stairs_glass", "Syn vytiahne pohár zo skrinky, doleje a berie ho hore, do svojej izby.", clock="20:29",
    sfx=[(0.4, "cabinet", 0.6), (1.4, "pour", 0.7)])
add("garage_door", "ŠTRNG. ŠTRNG.", "sound", dur=3.6, sfx=[(0.4, "rattle"), (1.8, "rattle")])
add("garage_door", "Pomaly. V rytme. Ako metronóm.", move="still", sfx=[(0.3, "rattle", 0.8), (1.9, "rattle", 0.8)])

# --- 7. The son's room ---------------------------------------------------------------------------
heading("7. INT. SYNOVA IZBA — NOC", "room")
add("attic_room", "Tridsaťtri rokov a celý jeho život sa zmestí do dvanástich štvorcových metrov v cudzom dome.", clock="20:31")
add("key_turn_inside", "Zaváha. Potom kľúč otočí. Potichu, aby to nebolo počuť.", sfx=[(1.5, "key_turn", 0.4)])
add("son_bed_glass", dur=3.5, move="in")
add("hallway_window", "CVAK.", "sound", dur=2.6, clock="20:35", sfx=[(0.5, "cvak_far")])
add("son_bed_glass", "CVAK. CVAK.", "sound", dur=2.6, clock="20:38", move="still", sfx=[(0.4, "cvak_far"), (1.0, "cvak_far")])
add("son_bed_glass", "Vchodové dvere. Znova. Tretíkrát za večer.", clock="20:41", sfx=[(0.3, "cvak_far")])
add("stairs_dark", "Otec ide hore. Ôsmy schod vŕzga. Syn to vie. Otec to vie.", clock="20:44",
    sfx=[(0.3, "step_soft"), (0.9, "step_soft"), (1.5, "stair_creak"), (2.1, "step_soft"), (2.7, "step_soft")])
add("hallway_window", "CVAK.", "sound", dur=2.6, clock="20:46", move="still", sfx=[(0.4, "cvak", 0.7)])
add("door_gap", "Kroky zastanú pred jeho dverami.", clock="20:47:00", sfx=[(0.2, "shuffle"), (0.8, "shuffle")], bed="heart")
add("door_gap", dur=3.5, move="still", sfx=[(1.0, "floor_creak")])
add("handle_inside", "Otcova ruka sa dotkne kľučky. Synov dych sa zastaví v polovici nádychu.", clock="20:47:04")
add("handle_inside", "Kľučka pomaly klesá. Narazí na zamknutý zámok.", clock="20:47:06", move="still",
    sfx=[(0.3, "handle_slow"), (1.6, "lock_bump")])
add(VEO_CLIP, clock="20:47:09", sfx=[(1.5, "handle_shake"), (4.6, "handle_shake", 0.8)])
add("son_jaw", "Čeľusť. Zuby sa stretnú. Nad uchom vystúpi sval ako povraz.", clock="20:47:12", sfx=[(0.4, "lock_bump", 0.7)])
add("handle_inside", "Kľučka hore. A hneď znova dole. Ešte pomalšie.", clock="20:47:14", move="in",
    sfx=[(0.3, "cvak", 0.7), (1.4, "handle_slow"), (2.8, "lock_bump")])
add("son_chest", "Hruď. Akoby mu niekto pod rebrami utiahol remeň o jednu dierku. A o ďalšiu.")
add("father_hall_face", "Na otcovej tvári nie je hnev. Je tam niečo horšie — pokoj nasýteného človeka.", clock="20:47:20")
add("father_hall_face", "Vie, že syn je za dverami a nespí. Vie, že sa pozerá na kľučku. Práve preto ju drží.", move="still")
add("knuckles_glass", "Biele kĺby. Presne ako na hrnčeku v kancelárii.")
add("door_gap", "Otec pustí kľučku. Nezaklope. Nepovie ani slovo. Stále stojí za dverami.", clock="20:47:31", dur=7,
    sfx=[(0.3, "cvak", 0.8), (4.5, "floor_creak", 0.8)])
add("father_walks_away", dur=4.5, clock="20:47:58", bed="room",
    sfx=[(0.2, "shuffle"), (0.9, "shuffle"), (1.6, "shuffle", 0.8), (3.2, "door_close", 0.45)])
add("attic_room", "Ticho. Obchôdzka trvala tridsať minút.", clock="20:51", move="out")
add("son_body_map", "Hnev v ňom nevypne. Vie presne, čo sa tu deje. Vie, že jeho otec je v tejto chvíli maniak.")
add("son_body_map", "A to vedomie mu nepomáha. Pravda, ktorú nemôže nikomu povedať, sa mení na ďalší tlak.", move="still")
vo("son_bed_glass", "Čo hľadáš? Čo tu do pekla hľadáš? Čo chceš nájsť? Mňa? Tak tu som! Tu som!", move="in")
add("son_bed_glass", "Výkrik existuje iba vo vnútri. Navonok nepohne ani perou.", move="still")
add("son_body_map", "A tak sa ten tlak, ako vždy, otočí. Dovnútra.", move="in")
add("son_neck", "Krk — stuhnutý ako drevo.", dur=2.8)
add("son_jaw", "Čeľusť — ráno ho budú bolieť zuby.", dur=3)
add("son_chest", "Hruď — nádych končí v polovici a ďalej to nejde.", dur=3.4)
add("son_body_map", "Žalúdok — kameň.", dur=2.8, move="still")
add("son_body_map", "Hnev, ktorý patril otcovi, si telo uloží ako do skladu, ktorý nikto nevyváža.", move="out")
add("silence_office", dur=1.0, fx="bright", bed="silence_day", move="still")
add("son_body_map", "Tentoraz ten obraz zastaví sám. Rýchlo. Zvyknuto. Vina prišla skôr ako obraz.", bed="room", move="in")
add("son_drinks", "Napije sa. Dlho.", dur=3.5)
vo("son_drinks", "Prvý pohár bol na to, aby si prežil tú hodinu. Druhý je na to, aby si prestal počuť kľučku, "
   "ktorá sa už nehýbe.", move="still")
add("bottle_level", "Doleje si. Tretí.", sfx=[(0.4, "pour")])
add("son_drinks", "Hučanie v hlave konečne ustúpi. Ramená klesnú. Čeľusť povolí.", bed="relief", move="out")
add("son_drinks", "Úľava z alkoholu a úľava z obrazu otcovej smrti znejú rovnako. Sú to jediné dva východy, ktoré pozná.",
    move="still", dur=7)

# --- 8. Night ----------------------------------------------------------------------------------------
heading("8. INT. SYNOVA IZBA — NOC", "night")
add("empty_glass", dur=3.5, clock="02:14", move="in")
add("son_bed_night", "Nespí. Alebo spí tak, ako spí niekto, kto celý život počúva.")
add("son_bed_night", "CVAK.", "sound", dur=2.8, move="still", sfx=[(0.5, "cvak_far")])
add("son_bed_night", "CVAK. CVAK.", "sound", dur=2.8, move="in", sfx=[(0.3, "cvak_far"), (1.0, "cvak_far")])
add("son_bed_night", "Otec robí obchôdzku aj o druhej v noci.", move="still")
add("son_bed_night", "Pery sa mu bezhlasne pohnú. Počíta. Vie presne, koľko ich ešte bude.", move="in")
add(None, "CVAK.", "sound", dur=3, sfx=[(0.4, "cvak_far")])

# --- 9. Morning ----------------------------------------------------------------------------------
heading("9. INT. OTCOV DOM — KUCHYŇA — RÁNO", "morning")
add("morning_kitchen", "Otec je oholený, v čistej košeli. Vyzerá ako človek, ktorý sa dobre vyspal.", clock="06:40")
add("shaking_hand_coffee", "Ruka sa mu nepatrne chveje. Lyžička cinkne o okraj šálky — dvakrát.",
    sfx=[(1.6, "spoon"), (2.1, "spoon", 0.8)])
line("father_newspaper", "OTEC (nezdvihne zrak)", "Zase si pil.")
add("father_newspaper", "Nie je to otázka.", dur=2.8, move="still", sfx=[(1.2, "page")])
line("father_newspaper", "OTEC", "Aj na tú bránu si bol včera opitý?", move="in")
add("son_morning", "Včera o 17:46 nepil. Vie to. Pamätá si to.")
add("son_morning", "Ale už necíti, či si to pamätá.", move="still")
add("son_morning", "Aj to jediné, čím prežil noc, sa stalo dôkazom proti nemu.", move="in")
line("son_morning", "SYN (do šálky)", "Prepáč.", dur=2.8, move="still")
line("father_keys_morning", "OTEC", "Ja už idem do firmy.", sfx=[(0.3, "chair"), (1.3, "keys")])
add("father_sits_again", dur=4.5, sfx=[(0.6, "chair"), (2.4, "page")])
add("son_looks_at_father", dur=6, bed="hallucination", move="in")
add(None, "RITUÁL KONTROLY", "title", dur=6, bed="black")
add(None, "Animatik. Obrazy: SDXL-Turbo. Záber v scéne 7: Veo 3.1 Fast.\nZvuk syntetizovaný v Pythone.", "action",
    dur=5, bed="black")
