import base64
import md5
import operator
import time

from django.db.models.query import Q
from django.conf import settings

from openid.association import Association as OIDAssociation
from openid.store.interface import OpenIDStore
from openid.store.nonce import SKEW
from openid.yadis import xri

from models import Association, Nonce


class OpenID:
    def __init__(self, openid, issued, attrs=None, sreg=None):
        self.openid = openid
        self.issued = issued
        self.attrs = attrs or {}
        self.sreg = sreg or {}
        self.is_iname = (xri.identifierScheme(openid) == 'XRI')

    def __repr__(self):
        return '<OpenID: %s>' % self.openid

    def __str__(self):
        return self.openid


class DjangoOpenIDStore(OpenIDStore):
    def __init__(self):
        self.max_nonce_age = 6 * 60 * 60 # Six hours

    def storeAssociation(self, server_url, association):
        assoc = Association(
            server_url=server_url,
            handle=association.handle,
            secret=base64.encodestring(association.secret),
            issued=association.issued,
            lifetime=association.issued,
            assoc_type=association.assoc_type)
        assoc.save()

    def getAssociation(self, server_url, handle=None):
        assocs = []
        if handle is not None:
            assocs = Association.objects.filter(
                server_url=server_url, handle=handle)
        else:
            assocs = Association.objects.filter(server_url=server_url)
        associations = []
        expired = []
        for assoc in assocs:
            association = OIDAssociation(
                assoc.handle, base64.decodestring(assoc.secret), assoc.issued,
                assoc.lifetime, assoc.assoc_type
            )
            if association.getExpiresIn() == 0:
                expired.append(assoc)
            else:
                associations.append((association.issued, association))
        for assoc in expired:
            assoc.delete()
        if not associations:
            return None
        associations.sort()
        return associations[-1][1]

    def removeAssociation(self, server_url, handle):
        assocs = list(Association.objects.filter(
            server_url=server_url, handle=handle))
        assocs_exist = len(assocs) > 0
        for assoc in assocs:
            assoc.delete()
        return assocs_exist

    def useNonce(self, server_url, timestamp, salt):
        if abs(timestamp - time.time()) > SKEW:
            return False

        try:
            ononce = Nonce.objects.get(
                server_url__exact=server_url,
                timestamp__exact=timestamp,
                salt__exact=salt)
        except Nonce.DoesNotExist:
            ononce = Nonce(
                server_url=server_url,
                timestamp=timestamp,
                salt=salt)
            ononce.save()
            return True

        return False

    def cleanupNonces(self):
        now = int(time.time())
        expired = Nonce.objects.filter(
            Q(timestamp__lt=now - SKEW) | Q(timestamp__gt=now + SKEW))
        count = expired.count()
        if count:
            expired.delete()
        return count

    def cleaupAssociations(self):
        now = int(time.time())
        expired = Association.objects.extra(
            where=['issued + lifetime < %d' % now])
        count = expired.count()
        if count:
            expired.delete()
        return count


def from_openid_response(openid_response):
    issued = int(time.time())
    return OpenID(
        openid_response.identity_url, issued, openid_response.signed_fields, 
        openid_response.extensionResponse('sreg', False)
    )
