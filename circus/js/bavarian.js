// Bavarian dialect response engine.
// Detects intent from German input, responds in authentic Bavarian dialect.
// Responses are circus-state-aware where relevant.

// ── Intent library ────────────────────────────────────────────────────────
const INTENTS = [
  {
    id: "greeting",
    keywords: ["hallo", "guten tag", "guten morgen", "guten abend", "hi", "hey",
               "servus", "grüß", "grüss", "moin", "grüezi", "habedere"],
    responses: [
      "Servus und herzlich willkommen beim Zirkus, Oida! Schee, dass'd kemma bist! 🎪",
      "Griaß di, du Schlingel! Setz di her und schau da des Spektakel aa! 🤹",
      "Na Servus! Endlich kimmt a Gscheita! Mia freun uns scho narrisch auf di! 🎭",
      "Habedere! Schee, schee, schee – willkommen in unserem Zirkus ohne Leid und mit vui Gaudi! 🎪",
      "Griaß Gott, Bua! Oda bist a Dirndl? Wurscht, du bist herzlich willkommen, Hauptsach du hast Spaß! 😄",
    ],
  },
  {
    id: "farewell",
    keywords: ["tschüss", "tschau", "auf wiedersehen", "ciao", "bye", "adieu",
               "pfiat", "lebwohl", "bis bald", "bis später"],
    responses: [
      "Pfiat di Gott, Oida! Kumm boid wieda, der Zirkus freut si scho auf di! 👋",
      "Servus und auf Wiederluagn! Pass auf di auf, gell, und ned z' vui aufs Handy schaugn! 📱",
      "Ha, gehst scho? Na ja, des is hoid so. Pfiat di und kumm wieda wenn'd magst! 🎭",
      "Ade, du Spezl! Des war a Gaudi mit dir – bis zum nächsten Moi! 🎪",
    ],
  },
  {
    id: "animals",
    keywords: ["tier", "tiere", "elefant", "elefanten", "tiger", "pferd", "pferde",
               "taube", "tauben", "animal", "zoo", "wildtier"],
    responses: [
      "Oida, bei uns san d' Tier des Heiligste! D' Elefantn hom ihren aigenen Auslauf, de Tiger hom a Gehege wia im Dschungel – koa Käfig, koa Dressurzwang, nix da! 🐘🐯",
      "Geh bitte, mia behandeln d' Tier mit so vui Liab! Nur Positiv-Training, freiwillige Teilnahm, und d' Rösser tanzn ganz ohne Reita. Des nennt man Liberty-Training, Oida! 🐴",
      "Des mit unsere Tier is a Herzensangelegenheit! D' Taubn fliegn frei ins Dach – aber koa Käfig. D' Elefantn schlendernd entspannt, ned abgerichtet. Bassd scho! 🕊️",
      "Mia san stolz drauf, dass bei uns koa einzigs Tier leidet! A Schmarrn is des mit dem alten Zirkus – wir machens anders, und zwar gscheit! 💪",
    ],
  },
  {
    id: "elephant",
    keywords: ["elefant", "elefanten", "rüssel", "dickhäuter"],
    responses: [
      "Oida, unsere Elefantn san absolute Stars! Die wandern ganz gemütlich durch ihr Habitat, und a Ranger erzählt dabei Gschichtl über Schutzprojekte in Afrika. Gänsehaut, Oida! 🐘",
      "D' Elefantn san d' sanftesten Riesen, de's gibt! Koa Kunststückl, koa Peitschn – nur Freiheit und Würd. Des is unsere Philosophie! 🐘💚",
    ],
  },
  {
    id: "horse",
    keywords: ["pferd", "pferde", "ross", "rösser", "hengst", "stute", "reiter", "liberty"],
    responses: [
      "Aaah, d' Liberty-Rösser! Des is a Augenweide, Oida! Die Pferde bewegen si ganz frei, ohne Reita – nur mit kloane Handzeichen, die mia mit vui Geduld und Liab eintrainiert hom. A Wahnsinn! 🐴",
      "Bei unsere Rösser gibt's koa Sporn, koa Peitschn, nix da! Reine positive Verstärkung – und trotzdem tanzn die wia professionelle Balletttänzer. Leiwand, oder?! 🐴",
    ],
  },
  {
    id: "political_left",
    keywords: ["liberal", "links", "linke", "grün", "grüne", "spd", "sozial",
               "öko", "ökologisch", "demokrat", "progressiv", "umwelt"],
    responses: [
      "Jo eh, d' linksliberalen Gäst – negatives DW-NOMINATE, wenn'd so wuist – die reißns bei der Umwelt-Show und der Elefantn-Führung! Des is wissenschaftlich bewiesen bei uns! 📊",
      "Scho klar, Oida! Wer auf d' linke Seit schaut, der kriagt bei unserer Umwelt-Gschicht und der Tier-Bildung volle Zufriedenheits-Punkte. Gaussian-Kurve schaut des scho! 🌍",
      "D' progressivn Gäst, DW-NOMINATE unter minus null Komma fünf, de san verrückt nach unserer Multicultural-Tanzrevue und dem Umwelt-Storytelling. Bassd scho bei denen! 🌿",
    ],
  },
  {
    id: "political_right",
    keywords: ["konservativ", "rechts", "rechte", "csu", "cdu", "tradition",
               "heimat", "patriot", "patriotisch", "national", "traditionell"],
    responses: [
      "Na sicher, d' Konservativn – positiver DW-NOMINATE-Wert – de reißns bei unserer Blaskapell und beim Patriotischen Finale! Wenn d' Trommeln dröhnen, explodiert der Zufriedenheits-Index! 🎺🎆",
      "Gwiß, Oida! Wer auf Heimat und Brauchtum schwört, dem gfallt d' Reiterballett und d' Marschkapell am besten bei uns. Des Gauß'sche Kurverl zeigt's ganz deutlich! 🐴🎺",
      "Freili! Die traditionell eingestellten Besucher – DW-NOMINATE über plus null Komma fünf – kriagen beim Patriotischen Finale richtig Gänsehaut. Des Befriedigungs-Gauß kippt dann nach rechts! 🎆",
    ],
  },
  {
    id: "phone",
    keywords: ["handy", "telefon", "smartphone", "bildschirm", "screen",
               "instagram", "tiktok", "social media", "facebook", "twitter",
               "posten", "handy-meter", "telefon-meter", "phone-meter", "gaugerl"],
    responses: [
      "Geh weg mit dem Handy, Oida! Schau auf d' Manege! Bei uns sinkt d' Handy-Sucht um bis zu 60 Prozent – des zeigt unser Meter ganz genau! 📱❌",
      "Des Handy kannst ruhig in d' Hosntasch steckn! Bei uns is so vui los, dass'd gar ned draan denkst. Des Phone-Urgn-Gaugerl zeigt's scho – je mehr Gaudi, desto weniger Handy-Zwickn! 🎪",
      "A Schmarrn ist des Handy-Glotzn! Unser Zirkus macht, dass d' Leut den Kopf wieder hochheben. Beim Aerial Trapeze vergisst wirklich jeda sein Smartphone – I schwör's! 🤸",
    ],
  },
  {
    id: "dwnominate",
    keywords: ["dw-nominate", "dwnominate", "nominate", "jeffrey lewis", "lewis",
               "ucla", "poole", "rosenthal", "political", "politisch", "skala", "score"],
    responses: [
      "Ha, des DW-NOMINATE is a gscheite Sach vom Jeffrey Lewis drübn in UCLA! Des misst d' politische Ideologie auf aner Skala von minus eins bis plus eins. Links is negativ, rechts is positiv – so wia bei uns im Zirkus! 📊",
      "Oida, des DW-NOMINATE-System vom Poole und Rosenthal – weiterentwickelt vom Lewis in LA – is des goldene Maß für politische Ideologie! Bei uns san d' Besucherln nach N-Null-Eins verteilt. Ganz schee statistisch, gell! 🎓",
      "Des is a Messsystem für politische Ideologie, Oida! Minus eins is erzliberal, plus eins is erzkonservativ. Mia nutzen des bei uns, damit's Zufriedenheits-Modell a wissenschaftliche Grundlage hot. Ned bloß dahergeredet! 📐",
    ],
  },
  {
    id: "gaussian",
    keywords: ["gauß", "gauss", "normalverteilung", "kurve", "gaussian", "glockenkurve",
               "zufriedenheit", "zufrieden", "satisfaction", "sigma", "statistik"],
    responses: [
      "Jo, des Gauß'sche Glockerl! S von Theta, v und Sigma gleich exp von minus Theta minus v Quadrat durch zwei Sigma-Quadrat – des is unsere Zufriedenheits-Formel! Klingt kompliziert, is aber eigentlich logisch: wer politisch ähnlich denkt wia der Akt, der ist zufriedener! 📊",
      "Oida, des Gauß-Kurverl is eigentlich ganz simpel: Je näher dein DW-NOMINATE-Wert am politischen Valenz-Wert vom Akt, desto glücklicher bist! Des Sigma gibt an, wia breit d' Kurv is – großes Sigma heißt breite Anziehungskraft! 🎯",
      "Ha, d' Normalverteilung und des Modell des freut mi, dass'd fragst! Wenn der Akt politisch neutral is – wia unser Aerial Trapeze – dann profitiertn ois Besucherln gleich. Des zeigt d' breite flache Kurv! 🤸",
    ],
  },
  {
    id: "trapeze",
    keywords: ["trapez", "trapeze", "luftnummer", "akrobat", "akrobatik", "luftartistik", "fliegen"],
    responses: [
      "Aaah, des Aerial Trapeze, des is d' Königin aller Vorstellungen! 30 Meter über der Manege, Oida – da hört das Herz kurz auf zu schlagen! Und weißt warum's so gut funktioniert? Wei's kein politisches Pickerl braucht – des gfallt ois! 🎪",
      "Des Trapeze is unser neutralster Akt – politische Valenz von null, breites Sigma. Egal ob du links oder rechts stehst, der Anblick von fliegendn Menschen macht jeden sprachlos. Schmarrn is, wer des ned toll findt! 🤸",
    ],
  },
  {
    id: "acrobatics",
    keywords: ["akrobat", "akrobatik", "jongleur", "jonglieren", "turnen", "sport",
               "kontortion", "körperkunst"],
    responses: [
      "Mia hom d' besten Akrobaten der Welt, Oida! 12 Nationen, ein Zirkus. Des internationale Akrobaten-Ensemble macht menschliche Türme, die höher san wia a Wirtshaus-Kasten! 🤸",
      "D' Jongleure und Akrobaten – des san alles Meister ihres Fachs, Oida! Hunderte von Stunden Training, und dann macht's des ganz locker aussegn. Leiwand is des! 🤹",
    ],
  },
  {
    id: "clown",
    keywords: ["clown", "clowns", "komik", "komiker", "witzig", "lachen", "humor"],
    responses: [
      "Oida, unser Contemporary Clown is ned so a kitschige Figur wia friaher! Des is modernes physisches Theater – koa aufgmoite Schuah, koa Rassismus, nur g'scheiter Humor! 🤡",
      "D' Clown-Show is inklusiv und herzlich, Oida! Ned auf Kosten von anderen lachen – des war imma d' Prämisse bei uns. Und weißt was? Es funktioniert! D' Leut lachen trotzdem, und noch lauter! 😄",
    ],
  },
  {
    id: "magic",
    keywords: ["magie", "magic", "zauberer", "illusionist", "trick", "illusion", "zauberei", "zaubern"],
    responses: [
      "Ha, der Zauberer! Alte Klassiker neu inszeniert, Oida! Und d' Taubn – de fliegen wirklich frei in die Kuppel, koa Käfig danach! D' Illusion lebt, und d' Tier aa! 🎩",
      "Des Magic-und-Illusions-Spektakel is a Gänsehaut-Programm, Oida! Des Publikum kapiert's bis heute ned, wia des geht. Und des is gut so! A bisserl Geheimnis muss sei'! 🪄",
    ],
  },
  {
    id: "environment",
    keywords: ["umwelt", "klima", "klimawandel", "natur", "ökologie", "nachhaltig",
               "conservation", "schutz", "artenschutz"],
    responses: [
      "Gott sei Dank fragst nach der Umwelt-Show! Des is eine von unseren Herzensvorstellungen. Projektions-Mapping, Live-Erzählung – d' Leut kommen raus und denken über Klimawandel nach. Mission erfüllt, Oida! 🌍",
      "D' Umwelt-Show is natürlich politisch a bisserl links positioniert – Valenz von minus null Komma fünf. Aber weißt was, des is ned Ideologie, des is Wissenschaft! D' Konservativen schauen a bissel kritischer, oba wenige bleiben unberührt! 🌿",
    ],
  },
  {
    id: "marching_band",
    keywords: ["blaskapelle", "blasmusik", "kapelle", "marschkapelle", "marsch",
               "brass", "trompete", "posaune", "tuba", "parade"],
    responses: [
      "Oida, d' Blaskapell is a Erlebnis! 60 Mann, eine Kapelle, und der Rhythmus geht so tief rein, dass'd unwillkürlich mitklatscht! Beim rechts-orientierten Publikum gehen die Zufriedenheits-Werte durch d' Decke! 🎺",
      "D' Marschkapell-Parade is traditionell und stolz – politische Valenz plus null Komma drei. Wer Blasmusik liebt, der is von uns bedient! Und wer's ned mag, der genießt wenigstens d' Rhythmik! 🥁",
    ],
  },
  {
    id: "patriotic",
    keywords: ["patriotisch", "patriot", "finale", "american", "amerikanisch",
               "heimat", "fahne", "flagge", "nationalismus"],
    responses: [
      "Des Patriotische Finale is unser krönender Abschluss – Americana pur, Oida! Fanfarn, Flaggen, Gemeinschaftsgefühl. DW-NOMINATE plus null Komma vier – des is deutlich auf d' rechte Seit positioniert! 🎆",
      "Ha, beim Patriotischen Finale san d' konservativen Besucherln absolut glücklich – aber auch viele Moderate sind ergriffen. Nur die ganz linken Ausreißer schauen da a bissel skeptisch. Des zeigt des Gauß-Modell wunderschön! 🇺🇸",
    ],
  },
  {
    id: "dance",
    keywords: ["tanz", "tanzen", "tänzer", "revue", "multikulturell", "international", "kultur"],
    responses: [
      "Unsere Multicultural-Tanzrevue is a Weltreise in 20 Minuten, Oida! Sechs Kontinente, eine Bühne. Des gfallt vor allem den linksliberal Gesinnten – oba ehrlich gsagt gfallt's eigentlich ois! 💃",
      "D' Tänzer aus aller Welt – des is bei uns gelebte Vielfalt, koa Schlagwort! Politische Valenz minus null Komma zwoa – leicht links, aba breit aufgestellt. Wunderschön, Oida! 🌏",
    ],
  },
  {
    id: "science",
    keywords: ["wissenschaft", "wissenschaftlich", "physik", "chemie", "stem",
               "bildung", "lernen", "schule", "experiment"],
    responses: [
      "D' Science-Illusions-Show is unser heimlicher Favorit! D' Kinder kommen rein und glauben, sie sehen Zauberei – und gehen raus mit dem Wissen, wia Physik funktioniert. Unglaublich, gell?! 🔬",
      "Ha, des mit der Wissenschaft-Show is gschickt! Unterhaltung und Bildung in einem Paket, Oida! Ned wundern, dass d' linksliberal Gäst des besonders schätzen – Valenz minus null Komma fünfzehn! 🧪",
    ],
  },
  {
    id: "help",
    keywords: ["hilfe", "wie", "was bedeutet", "erkläre", "erklar", "verstehe",
               "versteh", "anleitung", "spielen", "wie funktioniert"],
    responses: [
      "Na klar helf i dir, Oida! Erstmal klickst auf 'Akt aufführen' und wählst an Akt aus. Dann segst im Scatter-Plot, wia d' Besucherln reagieren – links im Plot san d' Liberalen, rechts d' Konservativen, und d' Höhe zeigt d' Zufriedenheit! 🎪",
      "Des is eigentlich ganz simpel: Besucherln hom alle an politischen Score nach DW-NOMINATE, verteilt nach N-Null-Eins. Jeder Akt hat an politischen Valenz-Wert. D' Gauß-Kurv sagt, wer am glücklichsten is! 📊",
      "Geh, i erklär's kurz: Blaue Punkt san Liberal, rote san Konservativ, lila sind Moderate. Je höher im Scatter-Plot, desto zufriedener. Und des Handy-Gaugerl zeigt, ob d' Leut noch aufs Telefon schaun – je besser d' Show, desto weniger! 📱",
    ],
  },
  {
    id: "great",
    keywords: ["super", "toll", "prima", "wunderbar", "fantastisch", "klasse", "geil",
               "leiwand", "schön", "schee", "genial", "bravo", "gut"],
    responses: [
      "Freut mi, Oida! Jo, mia im Zirkus geben imma 100 Prozent! Wennst magst, schau no d' anderen Akte aa – jeder is a Erlebnis für sich! 🎪",
      "Na Servus, des hört ma gern! Bassd scho, Oida! Und vergiss ned: 'Run Full Show' klicken für die volle Erfahrung! 🎭",
      "Ha, des freut mi! Bei uns is jeder Akt mit Herzblut dabei – kein Tier wird g'quält, kein Mensch beleidigt, und trotzdem Gaudi vom Feinsten! 🌟",
    ],
  },
  {
    id: "bad",
    keywords: ["schlecht", "langweilig", "fad", "blöd", "schmarrn", "unsinn",
               "quatsch", "furchtbar", "schrecklich", "möchte"],
    responses: [
      "Na hoid die Gosch, Oida! Kein Zirkus ist perfekt, oba mia geben unser Bestes! Welcher Akt hat dir ned gfalln? Villeicht ko i's erklären! 😄",
      "Aha, a Kritiker! Gut, des brauchma aa, Oida! Sag ma, was'd verbessern wuaßt – i bin gespannt. Oda stagierst einfach an anderen Akt und schaust, ob's dann besser is! 🎭",
      "Geh, ned so streng, Oida! Bei uns steckt vui Arbeit dahinter. Oba klar, Geschmäcker san verschieden – des zeigt ja gerade unser Gauß-Modell so scheen! 📊",
    ],
  },
  {
    id: "children",
    keywords: ["kinder", "kind", "familie", "familien", "familienfreundlich", "baby",
               "jugend", "jugendlich", "jung", "alt"],
    responses: [
      "Freili is des familienfreundlich, Oida! Jeder Akt is für ois Altersgruppen geeignet – de Kleinen lieben d' Tiere und d' Clowns, d' Erwachsenen schätzen d' Akrobatik und d' komplexeren Akte. Für jeden is was dabei! 👨‍👩‍👧‍👦",
      "Ha, Kinder im Zirkus – des is a Herzensangelegenheit! Bei uns erleben d' Kleinen Tiere in Würde, lernen über Umwelt, und lachen beim Contemporary Clown. Koa Grusel, koa Angst – nur Gaudi! 🎠",
    ],
  },
  {
    id: "run_show",
    keywords: ["start", "starten", "beginnen", "anfangen", "vorführung",
               "show starten", "los gehts", "gemma", "jetzt"],
    responses: [
      "Na Gemma, Oida! Drück auf 'Run Full Show' – des startet ois 15 Akte hintereinander! Du wirst segn, wia d' Zufriedenheit rauf und runter geht je nach politischem Valenz vom Akt! 🎪",
      "Ja freilich, anfangen können mia sofort! Klick 'Run Full Show' und lehn di zurück – 15 Akte, 18 Sekunden, volle Gaudi! 🎭",
    ],
  },
  {
    id: "bavarian",
    keywords: ["bayerisch", "bayer", "bavaria", "münchen", "münchen", "oktoberfest",
               "bier", "lederhose", "dirndl", "weißwurst"],
    responses: [
      "Oida, natürlich red i Bayrisch – des is d' schönste Sprach der Welt, nach dem Lateinischen vielleicht! Servus aus München, oda wia mia sagn: Minga! 🥨",
      "Ha, Bayern ist d' Heimat! Wo sonst hast Weißwurst und Weltklasse-Zirkus gleichzeitig? Des passt scho, gell! Prost! 🍺",
      "Freilich, i bin stolzer Bayer! Bei uns sagt man ned 'nein', man sagt 'na'. Ned 'ich', sondern 'i'. Und ned 'nicht', sondern 'ned'. Bassd scho, Oida! 🎭",
    ],
  },
  {
    id: "cost",
    keywords: ["kosten", "kostet", "eintritt", "preis", "teuer", "billig",
               "ticket", "eintrittskarte", "karte", "euro", "geld",
               "bezahlen", "zahlen", "umsonst", "gratis", "frei"],
    responses: [
      "Geh, des is kostenlos, Oida! Des ist a digitaler Zirkus – koa Eintritt, koa Popcorn, koa Warteschlange! Nur Gaudi und Wissenschaft, und des umsonst! 🎪💚",
      "Nichts kostet des! Des is freie Unterhaltung und Bildung in einem. Und wennst wuaßt, kannst auf GitHub nachschaun – alles open source! Bassd scho! 💻",
    ],
  },
  {
    id: "statistics",
    keywords: ["statistik", "daten", "analyse", "modell", "mathematik", "formel",
               "berechnung", "wissenschaft", "prozent"],
    responses: [
      "Ha, d' Statistik! Des Herzstück vom Ganzen, Oida! N-Null-Eins-Verteilung für d' Besucherln, Gauß für d' Zufriedenheit, DW-NOMINATE als politischer Rahmen – des is sauber durchdacht! 📊",
      "Oida, des Modell is deterministisch und transparent! S von Theta, v, Sigma – alles nachvollziehbar. Koa Black Box, koa KI-Schmarrn, nur echte Mathematik! 📐",
    ],
  },
];

// Fallback responses when no intent matches
const FALLBACK_RESPONSES = [
  "Hm, des hob i jetzt ned ganz verstanden, Oida! Frag mich nochmal, oba auf Deutsch! I versuchs dann auf Bayrisch zu erklärer! 🤔",
  "Geh, des war a bisserl zu hoch für mi! Ko i dir anders helfen? Frag mich zum Beispiel über d' Akt, d' Tier, oda wie des Modell funktioniert! 🎪",
  "Na, da komm i jetzt ned ganz mit, Oida! Magst d' Frag nochmal anders formuliern? I bin zwar a Bayer, oba ned allwissend! 😄",
  "Schmarrn, des versteh i ned! Oba koa Problem – stell mir an anderen Frog, zum Beispiel über DW-NOMINATE oda unsere Tier! 🎭",
  "Ha, des is a gute Frog – leider weiß i's ned! Frog mich was über d' Show, d' Wissenschaft dahinter, oda unser Tier-Konzept! 🤹",
];

// ── Core functions ────────────────────────────────────────────────────────

function detectIntent(text) {
  const lower = text.toLowerCase().trim();
  let bestMatch = null;
  let bestScore = 0;

  for (const intent of INTENTS) {
    let score = 0;
    for (const kw of intent.keywords) {
      if (lower.includes(kw)) score++;
    }
    if (score > bestScore) {
      bestScore = score;
      bestMatch = intent;
    }
  }
  return bestScore > 0 ? bestMatch : null;
}

function pickRandom(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// Context-aware response: can reference current act and audience stats
function getBavarianResponse(germanText, state) {
  const intent = detectIntent(germanText);

  // Context injections for certain intents
  if (intent) {
    // If asking about "run show" and a show is already running
    if (intent.id === "run_show" && state && state.isRunning) {
      return "Oida, d' Show läuft scho! Schau da des an – d' Akte kommen einer nach dem anderen! Lehn di zurück und genieß! 🎪";
    }

    // If asking about phone and phones-away is already high
    if (intent.id === "phone" && state) {
      const away = Math.round((1 - audiencePhoneUrge(state.visitors)) * 100);
      if (away > 50) {
        return `Ha, schau da des Gaugerl aa! ${away}% vom Publikum hom ihr Handy scho wegglegt! Des Konzept funktioniert, Oida! 📉`;
      }
    }

    // If asking about an act and that act is currently staged
    if (state && state.activeAct) {
      const act = state.activeAct;
      if (intent.id === "trapeze" && act.id === "aerial_trapeze") {
        return `Ha, des Aerial Trapeze is grad auf der Bühne, Oida! Schau d' Scatter-Plot aa – alle Besucherln san hoch oben! Politische Valenz null, breites Sigma – des is der Universalakt! 🤸`;
      }
      if (intent.id === "patriotic" && act.id === "patriotic_finale") {
        return `Jo, des Patriotische Finale grad jetzt! Schau d' roten Punkte rechts im Plot – de san richtig happy! D' blauen links schauen a bissel skeptischer aus. Des Gauß-Modell in Aktion! 🎆`;
      }
      if (intent.id === "environment" && act.id === "environmental_story") {
        return `Servus, grad läuft d' Umwelt-Show! Schau links im Scatter-Plot – d' liberalen Besucherln san begeistert, d' Konservativen a bisserl weniger. Genau wia's des Modell vorhersagt! 🌍`;
      }
    }

    return pickRandom(intent.responses);
  }

  // No intent matched — context-aware fallback
  if (state && state.activeAct) {
    const act = state.activeAct;
    return `Hm, des hob i ned ganz kapiert, Oida! Oba schau – grad läuft "${act.name}". Des is politisch bei ${act.political_valence > 0 ? "plus" : ""} ${act.political_valence.toFixed(2)} positioniert. Schau d' Zufriedenheit im Plot! 🎪`;
  }

  return pickRandom(FALLBACK_RESPONSES);
}
