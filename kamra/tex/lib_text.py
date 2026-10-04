"""Guest e-mail texts in the six TEX languages (R-49). Values passed in are already
HTML-escaped by the caller; only the link is inserted as an attribute/URL."""

from __future__ import annotations

from html import escape

T: dict[str, dict[str, tuple[str, str]]] = {
	"booking_confirmed": {
		"en": ("Your booking {ref} at {hotel} is confirmed",
		       "Dear {name},<br><br>thank you — your booking <b>{ref}</b> at {hotel} is confirmed. Total: {total}."),
		"tr": ("{hotel} rezervasyonunuz {ref} onaylandı",
		       "Sayın {name},<br><br>teşekkür ederiz — {hotel} için <b>{ref}</b> numaralı rezervasyonunuz onaylandı. Toplam: {total}."),
		"de": ("Ihre Buchung {ref} im {hotel} ist bestätigt",
		       "Guten Tag {name},<br><br>vielen Dank — Ihre Buchung <b>{ref}</b> im {hotel} ist bestätigt. Gesamtbetrag: {total}."),
		"ru": ("Ваше бронирование {ref} в {hotel} подтверждено",
		       "Здравствуйте, {name}!<br><br>Спасибо — ваше бронирование <b>{ref}</b> в {hotel} подтверждено. Итого: {total}."),
		"ro": ("Rezervarea dvs. {ref} la {hotel} este confirmată",
		       "Stimate/Stimată {name},<br><br>vă mulțumim — rezervarea <b>{ref}</b> la {hotel} este confirmată. Total: {total}."),
		"pl": ("Twoja rezerwacja {ref} w {hotel} jest potwierdzona",
		       "Dzień dobry {name},<br><br>dziękujemy — Twoja rezerwacja <b>{ref}</b> w {hotel} jest potwierdzona. Razem: {total}."),
	},
	"booking_pending": {
		"en": ("Your booking {ref} at {hotel} is waiting for payment",
		       "Dear {name},<br><br>we have reserved your stay (<b>{ref}</b>, {total}). It is confirmed as soon as the payment is received."),
		"tr": ("{hotel} rezervasyonunuz {ref} ödeme bekliyor",
		       "Sayın {name},<br><br>konaklamanız ayrıldı (<b>{ref}</b>, {total}). Ödeme alındığında rezervasyonunuz onaylanır."),
		"de": ("Ihre Buchung {ref} im {hotel} wartet auf Zahlung",
		       "Guten Tag {name},<br><br>wir haben Ihren Aufenthalt reserviert (<b>{ref}</b>, {total}). Er ist bestätigt, sobald die Zahlung eingegangen ist."),
		"ru": ("Бронирование {ref} в {hotel} ожидает оплаты",
		       "Здравствуйте, {name}!<br><br>Мы зарезервировали ваше проживание (<b>{ref}</b>, {total}). Бронирование будет подтверждено после оплаты."),
		"ro": ("Rezervarea {ref} la {hotel} așteaptă plata",
		       "Stimate/Stimată {name},<br><br>am rezervat sejurul dvs. (<b>{ref}</b>, {total}). Rezervarea se confirmă imediat după primirea plății."),
		"pl": ("Rezerwacja {ref} w {hotel} czeka na płatność",
		       "Dzień dobry {name},<br><br>zarezerwowaliśmy Twój pobyt (<b>{ref}</b>, {total}). Zostanie potwierdzony po otrzymaniu płatności."),
	},
	"payment_received": {
		"en": ("Payment received — booking {ref} confirmed",
		       "Dear {name},<br><br>we received your payment. Your booking <b>{ref}</b> at {hotel} is confirmed."),
		"tr": ("Ödemeniz alındı — {ref} onaylandı",
		       "Sayın {name},<br><br>ödemeniz alındı. {hotel} için <b>{ref}</b> numaralı rezervasyonunuz onaylandı."),
		"de": ("Zahlung erhalten — Buchung {ref} bestätigt",
		       "Guten Tag {name},<br><br>wir haben Ihre Zahlung erhalten. Ihre Buchung <b>{ref}</b> im {hotel} ist bestätigt."),
		"ru": ("Оплата получена — бронирование {ref} подтверждено",
		       "Здравствуйте, {name}!<br><br>Мы получили оплату. Ваше бронирование <b>{ref}</b> в {hotel} подтверждено."),
		"ro": ("Plata a fost primită — rezervarea {ref} este confirmată",
		       "Stimate/Stimată {name},<br><br>am primit plata. Rezervarea <b>{ref}</b> la {hotel} este confirmată."),
		"pl": ("Płatność otrzymana — rezerwacja {ref} potwierdzona",
		       "Dzień dobry {name},<br><br>otrzymaliśmy płatność. Twoja rezerwacja <b>{ref}</b> w {hotel} jest potwierdzona."),
	},
	# B5: money that reached a booking whose time to pay had ended (kept off it, in reconciliation);
	# {next}: what happens to it (``AFTER_EXPIRY_NEXT``)
	"payment_after_expiry": {
		"en": ("About your payment for booking {ref} at {hotel}",
		       "Dear {name},<br><br>we received your payment of {total} for booking <b>{ref}</b> at {hotel}, but the "
		       "time to pay for the booking had ended before it was paid in full, so the booking could not be "
		       "confirmed.<br><br>{next}"),
		"tr": ("{hotel} {ref} numaralı rezervasyonunuzun ödemesi hakkında",
		       "Sayın {name},<br><br>{hotel} için <b>{ref}</b> numaralı rezervasyonunuza ait {total} tutarındaki ödemeniz "
		       "alındı; ancak rezervasyonun ödeme süresi, ödeme tamamlanmadan sona erdiği için rezervasyon "
		       "onaylanamadı.<br><br>{next}"),
		"de": ("Zu Ihrer Zahlung für die Buchung {ref} im {hotel}",
		       "Guten Tag {name},<br><br>wir haben Ihre Zahlung von {total} für die Buchung <b>{ref}</b> im {hotel} "
		       "erhalten. Die Zahlungsfrist der Buchung war jedoch abgelaufen, bevor sie vollständig bezahlt war, daher "
		       "konnte die Buchung nicht bestätigt werden.<br><br>{next}"),
		"ru": ("О вашей оплате бронирования {ref} в {hotel}",
		       "Здравствуйте, {name}!<br><br>Мы получили вашу оплату {total} за бронирование <b>{ref}</b> в {hotel}, "
		       "однако срок оплаты бронирования истёк до того, как оно было полностью оплачено, поэтому бронирование "
		       "не удалось подтвердить.<br><br>{next}"),
		"ro": ("Despre plata dvs. pentru rezervarea {ref} la {hotel}",
		       "Stimate/Stimată {name},<br><br>am primit plata dvs. de {total} pentru rezervarea <b>{ref}</b> la {hotel}, "
		       "însă termenul de plată al rezervării a expirat înainte ca aceasta să fie achitată integral, așa că "
		       "rezervarea nu a putut fi confirmată.<br><br>{next}"),
		"pl": ("W sprawie płatności za rezerwację {ref} w {hotel}",
		       "Dzień dobry {name},<br><br>otrzymaliśmy Twoją płatność {total} za rezerwację <b>{ref}</b> w {hotel}, "
		       "jednak termin płatności za rezerwację upłynął, zanim została ona w pełni opłacona, dlatego rezerwacja "
		       "nie mogła zostać potwierdzona.<br><br>{next}"),
	},
	# {expires}: until when the link can be paid (B6)
	"payment_link": {
		"en": ("Payment request from {hotel}", "Dear {name},<br><br>{hotel} asks you to pay {total} for {ref}. "
		                                       "The link is valid until {expires}."),
		"tr": ("{hotel} ödeme talebi", "Sayın {name},<br><br>{hotel}, {ref} için {total} tutarında ödeme talep ediyor. "
		                              "Bağlantı {expires} tarihine kadar geçerlidir."),
		"de": ("Zahlungsaufforderung von {hotel}", "Guten Tag {name},<br><br>{hotel} bittet Sie, {total} für {ref} zu "
		                                           "bezahlen. Der Link ist bis {expires} gültig."),
		"ru": ("Запрос на оплату от {hotel}", "Здравствуйте, {name}!<br><br>{hotel} просит вас оплатить {total} за {ref}. "
		                                      "Ссылка действительна до {expires}."),
		"ro": ("Cerere de plată de la {hotel}", "Stimate/Stimată {name},<br><br>{hotel} vă roagă să plătiți {total} "
		                                        "pentru {ref}. Linkul este valabil până la {expires}."),
		"pl": ("Prośba o płatność od {hotel}", "Dzień dobry {name},<br><br>{hotel} prosi o zapłatę {total} za {ref}. "
		                                       "Link jest ważny do {expires}."),
	},
}

# C-04 on the web (ADR-078): a one-time link to sign in, or to confirm joining, at {hotel}; {program}: the program's
# name; {minutes}: how long the link works. An address with no membership asked to sign in gets "member_none", with a
# link to joining and no token. No mail greets by a name: a visitor types the names for an address they may not own
# (review round 1)
T["member_sign_in"] = {
	"en": ("Your sign-in link for {hotel}",
	       "Hello,<br><br>use the button below to sign in to {program} at {hotel} and see your member prices. The link "
	       "works once, for {minutes} minutes. If you did not ask for it, you can ignore this e-mail."),
	"tr": ("{hotel} giriş bağlantınız",
	       "Merhaba,<br><br>{hotel} {program} üyeliğinize giriş yapmak ve üye fiyatlarınızı görmek için aşağıdaki düğmeyi "
	       "kullanın. Bağlantı bir kez ve {minutes} dakika boyunca çalışır. Bu bağlantıyı siz istemediyseniz bu e-postayı "
	       "dikkate almayın."),
	"de": ("Ihr Anmeldelink für {hotel}",
	       "Guten Tag,<br><br>mit der Schaltfläche unten melden Sie sich bei {program} im {hotel} an und sehen Ihre "
	       "Mitgliederpreise. Der Link funktioniert einmal, {minutes} Minuten lang. Wenn Sie ihn nicht angefordert haben, "
	       "können Sie diese E-Mail ignorieren."),
	"ru": ("Ваша ссылка для входа в {hotel}",
	       "Здравствуйте!<br><br>Нажмите кнопку ниже, чтобы войти в {program} отеля {hotel} и увидеть цены для "
	       "участников. Ссылка работает один раз в течение {minutes} минут. Если вы её не запрашивали, просто "
	       "проигнорируйте это письмо."),
	"ro": ("Linkul dvs. de conectare la {hotel}",
	       "Bună ziua,<br><br>folosiți butonul de mai jos pentru a vă conecta la {program} de la {hotel} și a vedea "
	       "prețurile de membru. Linkul funcționează o singură dată, timp de {minutes} minute. Dacă nu l-ați cerut, "
	       "puteți ignora acest e-mail."),
	"pl": ("Twój link do logowania w {hotel}",
	       "Dzień dobry,<br><br>użyj przycisku poniżej, aby zalogować się do {program} w {hotel} i zobaczyć ceny dla "
	       "członków. Link działa jeden raz przez {minutes} minut. Jeśli o niego nie prosiłeś, zignoruj tę wiadomość."),
}
T["member_join"] = {
	"en": ("Confirm that you join {program}",
	       "Hello,<br><br>use the button below to confirm that you join {program} at {hotel}. You are then a member "
	       "and see member prices at once. The link works once, for {minutes} minutes. If you did not ask for it, you can "
	       "ignore this e-mail: nothing happens."),
	"tr": ("{program} üyeliğinizi onaylayın",
	       "Merhaba,<br><br>{hotel} {program} programına katıldığınızı onaylamak için aşağıdaki düğmeyi kullanın. "
	       "Böylece üye olursunuz ve üye fiyatlarını hemen görürsünüz. Bağlantı bir kez ve {minutes} dakika boyunca "
	       "çalışır. Bu isteği siz yapmadıysanız bu e-postayı dikkate almayın: hiçbir şey değişmez."),
	"de": ("Bestätigen Sie Ihren Beitritt zu {program}",
	       "Guten Tag,<br><br>bestätigen Sie mit der Schaltfläche unten, dass Sie {program} im {hotel} beitreten. "
	       "Danach sind Sie Mitglied und sehen sofort Mitgliederpreise. Der Link funktioniert einmal, {minutes} Minuten "
	       "lang. Wenn Sie das nicht angefordert haben, ignorieren Sie diese E-Mail: Es geschieht nichts."),
	"ru": ("Подтвердите участие в {program}",
	       "Здравствуйте!<br><br>Нажмите кнопку ниже, чтобы подтвердить участие в {program} отеля {hotel}. После "
	       "этого вы станете участником и сразу увидите цены для участников. Ссылка работает один раз в течение {minutes} "
	       "минут. Если вы этого не запрашивали, проигнорируйте письмо: ничего не изменится."),
	"ro": ("Confirmați înscrierea în {program}",
	       "Bună ziua,<br><br>folosiți butonul de mai jos pentru a confirma înscrierea în {program} de la "
	       "{hotel}. Veți fi apoi membru și veți vedea imediat prețurile de membru. Linkul funcționează o singură dată, "
	       "timp de {minutes} minute. Dacă nu ați cerut acest lucru, ignorați e-mailul: nu se întâmplă nimic."),
	"pl": ("Potwierdź dołączenie do {program}",
	       "Dzień dobry,<br><br>użyj przycisku poniżej, aby potwierdzić dołączenie do {program} w {hotel}. Staniesz "
	       "się członkiem i od razu zobaczysz ceny dla członków. Link działa jeden raz przez {minutes} minut. Jeśli o to "
	       "nie prosiłeś, zignoruj tę wiadomość: nic się nie zmieni."),
}
T["member_none"] = {
	"en": ("About signing in at {hotel}",
	       "Hello,<br><br>someone asked to sign in to {program} at {hotel} with this e-mail, but it has no membership yet. "
	       "You can join with the button below and see member prices at once. If you did not ask for it, you can ignore "
	       "this e-mail."),
	"tr": ("{hotel} girişi hakkında",
	       "Merhaba,<br><br>bu e-posta adresiyle {hotel} {program} programına giriş yapılmak istendi, ancak bu adresle "
	       "henüz bir üyelik yok. Aşağıdaki düğmeyle programa katılabilir ve üye fiyatlarını hemen görebilirsiniz. Bu "
	       "isteği siz yapmadıysanız bu e-postayı dikkate almayın."),
	"de": ("Zur Anmeldung im {hotel}",
	       "Guten Tag,<br><br>jemand wollte sich mit dieser E-Mail bei {program} im {hotel} anmelden, sie hat aber noch "
	       "keine Mitgliedschaft. Mit der Schaltfläche unten können Sie beitreten und sehen sofort Mitgliederpreise. Wenn "
	       "Sie das nicht angefordert haben, können Sie diese E-Mail ignorieren."),
	"ru": ("О входе в {hotel}",
	       "Здравствуйте!<br><br>С этим адресом пытались войти в {program} отеля {hotel}, но участия пока нет. Вы можете "
	       "вступить по кнопке ниже и сразу увидеть цены для участников. Если вы этого не запрашивали, просто "
	       "проигнорируйте письмо."),
	"ro": ("Despre conectarea la {hotel}",
	       "Bună ziua,<br><br>cineva a cerut conectarea la {program} de la {hotel} cu acest e-mail, dar acesta nu are încă "
	       "o calitate de membru. Vă puteți înscrie cu butonul de mai jos și veți vedea imediat prețurile de membru. Dacă "
	       "nu ați cerut acest lucru, puteți ignora e-mailul."),
	"pl": ("W sprawie logowania w {hotel}",
	       "Dzień dobry,<br><br>ktoś chciał zalogować się do {program} w {hotel} tym adresem e-mail, ale nie ma on jeszcze "
	       "członkostwa. Możesz dołączyć przyciskiem poniżej i od razu zobaczyć ceny dla członków. Jeśli o to nie "
	       "prosiłeś, zignoruj tę wiadomość."),
}

# C-04h (owner, 2026-10-04): a join asked for an address whose membership staff ended with a rejoin blocked. Only the
# address's owner reads it; it carries no link (joining online is not possible for them)
T["member_blocked"] = {
	"en": ("About joining {program} at {hotel}",
	       "Hello,<br><br>someone asked to join {program} at {hotel} with this e-mail. This membership cannot be renewed "
	       "online: please contact the hotel if you would like to become a member again. If you did not ask for it, you "
	       "can ignore this e-mail."),
	"tr": ("{hotel} {program} üyeliği hakkında",
	       "Merhaba,<br><br>bu e-posta adresiyle {hotel} {program} programına katılmak istendi. Bu üyelik çevrimiçi "
	       "yenilenemez: yeniden üye olmak isterseniz lütfen otelle iletişime geçin. Bu isteği siz yapmadıysanız bu "
	       "e-postayı dikkate almayın."),
	"de": ("Zum Beitritt zu {program} im {hotel}",
	       "Guten Tag,<br><br>jemand wollte mit dieser E-Mail {program} im {hotel} beitreten. Diese Mitgliedschaft kann "
	       "nicht online erneuert werden: Bitte wenden Sie sich an das Hotel, wenn Sie wieder Mitglied werden möchten. "
	       "Wenn Sie das nicht angefordert haben, können Sie diese E-Mail ignorieren."),
	"ru": ("Об участии в {program} отеля {hotel}",
	       "Здравствуйте!<br><br>С этим адресом пытались вступить в {program} отеля {hotel}. Это участие нельзя "
	       "возобновить онлайн: если вы хотите снова стать участником, пожалуйста, свяжитесь с отелем. Если вы этого не "
	       "запрашивали, просто проигнорируйте письмо."),
	"ro": ("Despre înscrierea în {program} de la {hotel}",
	       "Bună ziua,<br><br>cineva a cerut înscrierea în {program} de la {hotel} cu acest e-mail. Această calitate de "
	       "membru nu poate fi reînnoită online: vă rugăm să contactați hotelul dacă doriți să deveniți din nou membru. "
	       "Dacă nu ați cerut acest lucru, puteți ignora e-mailul."),
	"pl": ("W sprawie dołączenia do {program} w {hotel}",
	       "Dzień dobry,<br><br>ktoś chciał dołączyć do {program} w {hotel} tym adresem e-mail. Tego członkostwa nie "
	       "można odnowić online: jeśli chcesz ponownie zostać członkiem, skontaktuj się z hotelem. Jeśli o to nie "
	       "prosiłeś, zignoruj tę wiadomość."),
}

LINK_LABEL = {
	"booking_confirmed": {"en": "View or change your booking", "tr": "Rezervasyonunuzu görüntüleyin veya değiştirin",
	                      "de": "Buchung ansehen oder ändern", "ru": "Посмотреть или изменить бронирование",
	                      "ro": "Vedeți sau modificați rezervarea", "pl": "Zobacz lub zmień rezerwację"},
	"booking_pending": {"en": "Complete or manage your booking", "tr": "Rezervasyonunuzu tamamlayın veya yönetin",
	                    "de": "Buchung abschließen oder verwalten", "ru": "Завершить или изменить бронирование",
	                    "ro": "Finalizați sau gestionați rezervarea", "pl": "Dokończ lub zarządzaj rezerwacją"},
	"payment_link": {"en": "Pay securely", "tr": "Güvenli ödeme yapın", "de": "Sicher bezahlen",
	                 "ru": "Оплатить безопасно", "ro": "Plătiți în siguranță", "pl": "Zapłać bezpiecznie"},
	"member_sign_in": {"en": "Sign in", "tr": "Giriş yap", "de": "Anmelden", "ru": "Войти", "ro": "Conectare",
	                   "pl": "Zaloguj się"},
	"member_join": {"en": "Confirm and join", "tr": "Onayla ve katıl", "de": "Bestätigen und beitreten",
	                "ru": "Подтвердить и вступить", "ro": "Confirmați și înscrieți-vă", "pl": "Potwierdź i dołącz"},
	"member_none": {"en": "Join the program", "tr": "Programa katıl", "de": "Dem Programm beitreten",
	                "ru": "Вступить в программу", "ro": "Înscrieți-vă în program", "pl": "Dołącz do programu"},
}

# what happens to money a booking could not take (B5): refunded by itself, or the hotel decides
AFTER_EXPIRY_NEXT = {
	"refund": {"en": "The payment will be refunded to you.", "tr": "Ödemeniz size iade edilecektir.",
	           "de": "Die Zahlung wird Ihnen erstattet.", "ru": "Оплата будет вам возвращена.",
	           "ro": "Plata vă va fi rambursată.", "pl": "Płatność zostanie Ci zwrócona."},
	"contact": {"en": "The hotel will contact you about this payment.",
	            "tr": "Otel bu ödemeyle ilgili sizinle iletişime geçecektir.",
	            "de": "Das Hotel wird sich wegen dieser Zahlung mit Ihnen in Verbindung setzen.",
	            "ru": "Отель свяжется с вами по поводу этой оплаты.",
	            "ro": "Hotelul vă va contacta în legătură cu această plată.",
	            "pl": "Hotel skontaktuje się z Tobą w sprawie tej płatności."},
}

FOOTER = {
	"en": "Keep this e-mail private: the link gives access to your booking.",
	"tr": "Bu e-postayı kimseyle paylaşmayın: bağlantı rezervasyonunuza erişim sağlar.",
	"de": "Bitte geben Sie diese E-Mail nicht weiter: Der Link gewährt Zugriff auf Ihre Buchung.",
	"ru": "Не пересылайте это письмо: ссылка даёт доступ к вашему бронированию.",
	"ro": "Păstrați acest e-mail privat: linkul oferă acces la rezervarea dvs.",
	"pl": "Nie udostępniaj tej wiadomości: link daje dostęp do Twojej rezerwacji.",
}


# a member link signs its holder in (it is no booking's): its own footer
MEMBER_FOOTER = {
	"en": "Keep this e-mail private: the link signs you in.",
	"tr": "Bu e-postayı kimseyle paylaşmayın: bağlantı sizin adınıza giriş yapar.",
	"de": "Bitte geben Sie diese E-Mail nicht weiter: Der Link meldet Sie an.",
	"ru": "Не пересылайте это письмо: ссылка выполняет вход от вашего имени.",
	"ro": "Păstrați acest e-mail privat: linkul vă conectează.",
	"pl": "Nie udostępniaj tej wiadomości: link loguje Cię na Twoje konto.",
}
FOOTERS = {"member_sign_in": MEMBER_FOOTER, "member_join": MEMBER_FOOTER, "member_none": {}, "member_blocked": {}}
# member mails that carry no link at all (C-04h)
NO_LINK = frozenset({"member_blocked"})


def render(key: str, lang: str, *, link: str = "", **values: str) -> tuple[str, str]:
	lang = lang if lang in T[key] else "en"
	subject_t, body_t = T[key][lang]
	subject = subject_t.format(**{k: v for k, v in values.items()})
	body = body_t.format(**values)
	if link:
		label = LINK_LABEL.get(key, {}).get(lang) or LINK_LABEL.get(key, {}).get("en", "Open")
		body += (f'<br><br><a href="{escape(link, quote=True)}" style="display:inline-block;padding:10px 16px;'
		         f'background:#2250d1;color:#fff;border-radius:8px;text-decoration:none">{label}</a>'
		         + (f'<br><br><small>{footer}</small>' if (footer := FOOTERS.get(key, FOOTER).get(lang)) else ""))
	# subjects are plain text: undo the HTML escaping done for the body
	from html import unescape

	return unescape(subject), body
