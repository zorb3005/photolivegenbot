from .start import Start
from .animate_photo import AnimatePhoto
from .format_select import FormatSelect

from app.bot.account.cabinet import Cabinet
from app.bot.account.topup import TopUp
from app.bot.account.referral import Referral
from app.bot.account.email_prompt import EmailForReceipt
from .support import Support
from .our_bots import OurBots
from app.bot.admin.paypfoto import AdminPayPfoto

ALL_PAGES = [
    Start(),
    AnimatePhoto(),
    FormatSelect(),
    Cabinet(),
    TopUp(),
    Referral(),
    EmailForReceipt(),
    Support(),
    OurBots(),
    AdminPayPfoto(),
]
