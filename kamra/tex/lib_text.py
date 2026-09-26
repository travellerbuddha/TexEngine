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

LINK_LABEL = {
	"booking_confirmed": {"en": "View or change your booking", "tr": "Rezervasyonunuzu görüntüleyin veya değiştirin",
	                      "de": "Buchung ansehen oder ändern", "ru": "Посмотреть или изменить бронирование",
	                      "ro": "Vedeți sau modificați rezervarea", "pl": "Zobacz lub zmień rezerwację"},
	"booking_pending": {"en": "Complete or manage your booking", "tr": "Rezervasyonunuzu tamamlayın veya yönetin",
	                    "de": "Buchung abschließen oder verwalten", "ru": "Завершить или изменить бронирование",
	                    "ro": "Finalizați sau gestionați rezervarea", "pl": "Dokończ lub zarządzaj rezerwacją"},
	"payment_link": {"en": "Pay securely", "tr": "Güvenli ödeme yapın", "de": "Sicher bezahlen",
	                 "ru": "Оплатить безопасно", "ro": "Plătiți în siguranță", "pl": "Zapłać bezpiecznie"},
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


def render(key: str, lang: str, *, link: str = "", **values: str) -> tuple[str, str]:
	lang = lang if lang in T[key] else "en"
	subject_t, body_t = T[key][lang]
	subject = subject_t.format(**{k: v for k, v in values.items()})
	body = body_t.format(**values)
	if link:
		label = LINK_LABEL.get(key, {}).get(lang) or LINK_LABEL.get(key, {}).get("en", "Open")
		body += (f'<br><br><a href="{escape(link, quote=True)}" style="display:inline-block;padding:10px 16px;'
		         f'background:#2250d1;color:#fff;border-radius:8px;text-decoration:none">{label}</a>'
		         f'<br><br><small>{FOOTER[lang]}</small>')
	# subjects are plain text: undo the HTML escaping done for the body
	from html import unescape

	return unescape(subject), body
