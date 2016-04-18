import os
import re
import functools
import tempfile

from zope.interface import Interface, Attribute, implementer
from twisted.internet import defer

# XXX
# think: port vs ports: and how do we represent that? i.e. if we
# decide "port" then we have to allow for multiple HiddenSerivce
# instances to have the same private key/hostname but different ports.

# XXX: what about 'detached' versus not onions...

# XXX: okay, so is this now just too many options in one factory
# function?

# XXX: so, should create_onion() "just" be a dispatcher to "more
# specific" factory-functions, like "create_ephemeral_onion"
# "create_detached_onion" "create_permanent_onion??" etc...?
# --> yes.
# --> also: direct people to Tor() thing (doesn't exist in this branch tho)


class HiddenServiceClientAuth(object):
    """
    Encapsulates a single client-authorization, as parsed from a
    HiddenServiceDir's "client_keys" file if you have stealth or basic
    authentication turned on.

    :param name: the name you gave it in the HiddenServiceAuthorizeClient line
    :param cookie: random password
    :param key: RSA private key, or None if this was basic auth
    """

    def __init__(self, name, cookie, key=None):
        self.name = name
        self.cookie = cookie
        self.key = parse_rsa_blob(key) if key else None


class IOnionService(Interface):
    """
    Encapsulates a single, ephemeral onion service.

    If this happens to be a filesystem-based service (instead of
    ephemeral), it shall implement IFilesystemOnionService as well
    (which is a subclass of this).

    If this object happens to represent an authenticated service, it
    shall implement IAuthenticatedOnionService ONLY (not this
    interface too; IAuthenticatedOnionService returns *lists* of
    IAuthenticatedOnionClient instances which are a subclass of
    IOnionService; see :class:`txtorcon.IAuthenticatedOnionService`).

    For non-authenticated services, there will be one of these per
    directory (i.e. HiddenServiceDir) if using non-ephemeral services,
    or one per ADD_ONION for ephemeral hidden services.

    For authenticated services, there is an instance implementing this
    interface for each "client" of the authenticated service. In the
    "basic" case, the .onion URI happens to be the same for each one
    (with a different authethentication token) whereas for a "stealth"
    sevice the .onion URI is different.
    """
    hostname = Attribute("hostname, including .onion")  # XXX *with* .onion? or not?
    private_key = Attribute("Private key blob (bytes)")
    ports = Attribute("list of str; the ports lines like 'public_port host:local_port'")


# class IFilesystemOnionService(Interface):
class IFilesystemOnionService(IOnionService):
    # XXX do we want to expose the directory in the API? probably...
    hidden_service_directory = Attribute('The directory where private data is kept')
    group_readable = Attribute("set HiddenServiceGroupReadable if true")


# XXX
class IAuthenticatedService(Interface):
    name = Attribute("which client is this")
    auth_token = Attribute("the keyz!!!")


@implementer(IFilesystemOnionService)
@implementer(IAuthenticatedService)
class AuthenticatedFilesystemOnionService(object):
    pass


@implementer(IFilesystemOnionService)
class FilesystemOnionService(object):
    pass


# XXX bad name? why isn't it something collection-releated
# e.g. IOnionServiceCollection ... or whatever bikeshed color
# just having "OnionSerivce" in this class name smells real bad, because it doesn't implement IOnionService
# maybe: IOnionClients? IOnionClientCollection?
# class IAuthenticatedOnionService(Interface):

class IOnionClients(Interface):
    """
    This encapsulates both 'stealth' and 'basic' authenticated Onion
    (nee Hidden) services, whether ephemeral or not. Note that Tor
    doesn't yet support ephemeral authenticated services.
    """

    def client_names(self):
        """
        :return: list of str instances, one for each client
        """

    def get_client(self, name):
        """
        :return: object implementing IOnionClient for the named client
        """

    def add_client(self, name):
        """
        probably returns a Deferred? god fucking knows
        """

    def del_client(self, name):
        """
        moar deferreds
        """


class IOnionClient(IOnionService):
    """
    A single client from a 'parent' IAuthenticatedOnionService. We do
    this because hidden services can have different URLs and/or
    auth_tokens on a per-client basis. So, the only way to access
    *anything* from an authenticated onion service is to list the
    cleints -- which gives you one IAuthenticatedOnionClient per
    client.
    """
    auth_token = Attribute('Some secret bytes')
    name = Attribute('str')  # XXX required? probably.
    # XXX do we want/need to reveal the "parent"
    # parent = Attribute("XXX?")


@implementer(IOnionService)
@implementer(IFilesystemOnionService)
class FilesystemHiddenService(object):
    """
    """
    def __init__(self, config, thedir, ports,
                 auth=None, ver=2, group_readable=0):
        if not isinstance(ports, list):
            raise ValueError("'ports' must be a list of strings")
        self._config = config
        self._dir = thedir
        from .torconfig import _ListWrapper
        self._ports = _ListWrapper(
            ports,
            functools.partial(config.mark_unsaved, 'HiddenServices'),
        )
        self._auth = auth
        if self._auth is None:
            self._auth = []
        self._version = ver
        self._group_readable = group_readable
        self._hostname = None
        self._private_key = None

    @property
    def auth_token(self):
        raise ValueError("FIXME")
    # can we reconcile this with the current API!? will NOT work for
    # stealth auth unless we fuxor around and make HiddenService
    # implement both interfaces :/

    @property
    def hostname(self):
        if self._hostname is None:
            with open(os.path.join(self._dir, 'hostname'), 'r') as f:
                self._hostname = f.read().strip()
        return self._hostname

    @property
    def private_key(self):
        if self._private_key is None:
            with open(os.path.join(self._dir, 'private_key'), 'r') as f:
                self._private_key = f.read().strip()
        return self._private_key

    @property
    def ports(self):
        return self._ports

    @ports.setter
    def ports(self, ports):
        # XXX FIXME need to update Tor's notion of config and/or
        # reject this request after we *have* updated Tor..."or
        # something"
        from .torconfig import _ListWrapper
        self._ports = _ListWrapper(
            ports,
            functools.partial(self._config.mark_unsaved, 'HiddenServices'),
        )
        self._config.mark_unsaved('HiddenServices')

    @property
    def dir(self):  # XXX propbably should be 'directory'?
        return self._dir

    @dir.setter
    def dir(self, d):
        self._dir = d  # XXX FIXME see above
        self._config.mark_unsaved('HiddenServices')

    @property
    def group_readable(self):
        return self._group_readable

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, v):
        self._version = v
        self._config.mark_unsaved('HiddenServices')

    @property
    def authorize_client(self):
        return self._auth

    # etcetc, basically the old "HiddenService" object

    def config_attributes(self):
        # XXX probably have to switch to "get_config_commands" or similar?
        # -> how to do ADD_ONION stuff, anyway?
        # -> hmm, could do helper methods, NOT member func (yes! <-- this one)

        rtn = [('HiddenServiceDir', str(self.dir))]
        if self._config._supports['HiddenServiceDirGroupReadable'] \
           and self.group_readable:
            rtn.append(('HiddenServiceDirGroupReadable', str(1)))
        for x in self.ports:
            rtn.append(('HiddenServicePort', str(x)))
        if self.version:
            rtn.append(('HiddenServiceVersion', str(self.version)))
        for authline in self.authorize_client:
            rtn.append(('HiddenServiceAuthorizeClient', str(authline)))
            # rtn.append(('HiddenServiceAuthorizeClient', str(self.authorize_client)))
        return rtn

    def config_commands(self):
        pass  # XXX FIXME


# XXX: probably better/nicer to make "EphemeralHiddenService" object
# "just" a data-container; it needs to list-wrapping voodoo etc like
# the others.
#   --> so only way to "add" it to a Tor is via a factory-method (like
#       from_ports() below, but with a better name)
#   --> so possibly only from create_onion_service()
#   --> ...which itself shold probably be "just" a dispatcher to "more
#       specific" factory-functions, like "create_ephemeral_onion"
#       "create_detached_onion" "create_permanent_onion??" etc...?

@implementer(IOnionService)
class EphemeralHiddenService(object):
    @classmethod
    @defer.inlineCallbacks
    def create(cls, config, ports,
               detach=False,
               discard_key=False,
               private_key=None):
        """
        returns a new EphemeralHiddenService after adding it to the
        provided config and ensuring at least one of its descriptors
        is uploaded.

        See also :meth:`txtorcon.create_onion_service` (which
        ultimately calls this).
        """
        if private_key and discard_key:
            raise ValueError("Don't pass a 'private_key' and ask to 'discard_key'")

        onion = EphemeralHiddenService(
            config, ports,
            hostname=None,
            private_key=private_key,
            detach=detach,
            discard_key=discard_key,
        )
        # XXX just use sets for this instead of lists?
        if onion not in config.EphemeralOnionServices:
            config.EphemeralOnionServices.append(onion)

        # we need to wait for confirmation that we've published the
        # descriptor to at least one Directory Authority. This means
        # watching the 'HS_DESC' event, but we do that right *before*
        # issuing the ADD_ONION command(s) so we can't miss one.
        uploaded = defer.Deferred()
        attempted_uploads = set()
        confirmed_uploads = set()
        failed_uploads = set()

        def hs_desc(evt):
            """
            From control-spec:
            "650" SP "HS_DESC" SP Action SP HSAddress SP AuthType SP HsDir
            [SP DescriptorID] [SP "REASON=" Reason] [SP "REPLICA=" Replica]
            """
            args = evt.split()
            subtype = args[0]
            if subtype == 'UPLOAD':
                if args[1] == onion.hostname[:-6]:
                    attempted_uploads.add(args[3])

            elif subtype == 'UPLOADED':
                # we only need ONE successful upload to happen for the
                # HS to be reachable.
                # unused? addr = args[1]
                if args[3] in attempted_uploads:
                    confirmed_uploads.add(args[3])
                    log.msg("Uploaded '{}' to '{}'".format(onion.hostname, args[3]))
                    uploaded.callback(onion)

            elif subtype == 'FAILED':
                if args[1] == onion.hostname[:-6]:
                    failed_uploads.add(args[3])
                    if failed_uploads == attempted_uploads:
                        msg = "Failed to upload '{}' to: {}".format(
                            onion.hostname,
                            ', '.join(failed_uploads),
                        )
                        uploaded.errback(RuntimeError(msg))

        yield config.tor_protocol.add_event_listener('HS_DESC', hs_desc)

        # okay, we're set up to listen, and now we issue the ADD_ONION
        # command. this will set ._hostname and ._private_key properly
        cmd = 'ADD_ONION {}'.format(onion.private_key or 'NEW:BEST')
        for port in ports:
            cmd += ' Port={},{}'.format(*port.split(' ', 1))
        flags = []
        if detach:
            flags.append('Detach')
        if discard_key:
            flags.append('DiscardPK')
        if flags:
            cmd += ' Flags={}'.format(','.join(flags))

        res = yield config.tor_protocol.queue_command(cmd)
        res = find_keywords(res.split('\n'))
        try:
            onion._hostname = res['ServiceID'] + '.onion'
            if discard_key:
                onion._private_key = None
            else:
                onion._private_key = res['PrivateKey']
        except KeyError:
            raise RuntimeError(
                "Expected ADD_ONION to return ServiceID= and PrivateKey= args"
            )

        log.msg("Created '{}', waiting for descriptor uploads.".format(onion.hostname))
        yield uploaded
        yield config.tor_protocol.remove_event_listener('HS_DESC', hs_desc)

        # XXX more thinking req'd
        # config.HiddenServices.append(onion)
        if onion not in config.EphemeralOnionServices:
            config.EphemeralOnionServices.append(onion)

        defer.returnValue(onion)
        return

    def __init__(self, config, ports, hostname=None, private_key=None, auth=[], ver=2,
                 detach=False, discard_key=False):
        # XXX do we need version?
        self._config = config
        self._ports = ports
        self._hostname = hostname
        self._private_key = private_key
        self._detach = detach
        self._discard_key = discard_key
        if auth != []:
            raise RuntimeError(
                "Tor doesn't yet support authentication on ephemeral onion "
                "services."
            )
        self._version = ver

    @property
    def hostname(self):
        return self._hostname

    @property
    def private_key(self):
        return self._private_key

    # Note: auth not yet supported by Tor, for ADD_ONION


@implementer(IOnionClient)
class AuthenticatedHiddenServiceClient(object):
    """
    A single client of an AuthenticatedHiddenService

    These are only created by and returned from the .clients property
    of an AuthenticatedHiddenService instance.
    """

    def __init__(self, parent, name, hostname, ports, token):
        self._parent = parent
        self._name = name
        self.hostname = hostname
        self.auth_token = token
        self.ephemeral = False
        self._ports = ports
        # XXX private_key?
        # XXX group_readable

    @property
    def ports(self):
        return self._ports

    @property
    def private_key(self):
        # yes, needs to come from "clients" file i think?
        return self._parent._private_key(self._name).key

    @property
    def group_readable(self):
        return self._parent.group_readable


@implementer(IAuthenticatedService)
class AuthenticatedHiddenService(object):
    """
    Corresponds to::

      HiddenServiceDir /home/mike/src/tor/hidserv-stealth
      HiddenServiceDirGroupReadable 1
      HiddenServicePort 80 127.0.0.1:99
      HiddenServiceAuthorizeClient stealth quux,flummox,zinga

    or::

      HiddenServiceDir /home/mike/src/tor/hidserv-basic
      HiddenServiceDirGroupReadable 1
      HiddenServicePort 80 127.0.0.1:99
      HiddenServiceAuthorizeClient basic foo,bar,baz
    """
    def __init__(self, config, thedir, ports, clients=None, ver=2, group_readable=0):
        # XXX do we need version here? probably...
        self._config = config
        self._dir = thedir
        self._ports = ports
        # dict: name -> IAuthenticatedOnionClient
        self._clients = None  # XXX validate vs. clients if not None?
        self._version = ver
        self._group_readable = group_readable
        self._client_keys = None

    # basically everything in HiddenService, except the only API we
    # provide is "clients" because there's a separate .onion hostname
    # and authentication token per client.

    def client_names(self):
        """
        IAuthenticatedOnionService API
        """
        if self._clients is None:
            self._parse_hostname()
        return self._clients.keys()

    def get_client(self, name):
        """
        IAuthenticatedOnionService API
        """
        if self._clients is None:
            self._parse_hostname()
        try:
            return self._clients[name]
        except KeyError:
            raise RuntimeError("No such client '{}'".format(name))

    def _private_key(self, name):
        if self._client_keys is None:
            self._parse_client_keys()
        return self._client_keys[name]

    def _parse_client_keys(self):
        with open(os.path.join(self._dir, 'client_keys'), 'r') as f:
            keys = parse_client_keys(f)
        self._client_keys = {}
        for auth in keys:
            self._client_keys[auth.name] = auth

    def _parse_hostname(self):
        clients = {}
        with open(os.path.join(self._dir, 'hostname')) as f:
            for idx, line in enumerate(f.readlines()):
                # lines are like: hex.onion hex # client: name
                m = re.match("(.*) (.*) # client: (.*)", line)
                hostname, cookie, name = m.groups()
                # -> for auth'd services we end up with multiple
                # -> HiddenService instances now (because different
                # -> hostnames)
                clients[name] = AuthenticatedHiddenServiceClient(
                    self, name, hostname,
                    ports=self._ports,
                    token=cookie,
                )
        self._clients = clients

    def config_attributes(self):
        """
        Helper method used by TorConfig when generating a torrc file.
        """

        rtn = [('HiddenServiceDir', str(self.dir))]
        if self.conf._supports['HiddenServiceDirGroupReadable'] \
           and self.group_readable:
            rtn.append(('HiddenServiceDirGroupReadable', str(1)))
        for port in self.ports:
            rtn.append(('HiddenServicePort', str(port)))
        if self.version:
            rtn.append(('HiddenServiceVersion', str(self.version)))
        for authline in self.authorize_client:
            rtn.append(('HiddenServiceAuthorizeClient', str(authline)))
        return rtn


def parse_rsa_blob(lines):
    return 'RSA1024:' + ''.join(lines[1:-1])


def parse_client_keys(stream):
    '''
    This parses a hidden-service "client_keys" file, either stealth or
    basic (they're the same, except "stealth" includes a
    "client-key"). Returns a list of HiddenServiceClientAuth() instances.

    Note that the key does NOT include the "----BEGIN ---" markers,
    nor *any* embedded whitespace. It is *just* the key blob.

    '''

    def parse_error(data):
        raise RuntimeError("Parse error at: " + data)

    class ParserState(object):
        def __init__(self):
            self.keys = []
            self.reset()

        def reset(self):
            self.name = None
            self.cookie = None
            self.key = []

        def create_key(self):
            if self.name is not None:
                self.keys.append(HiddenServiceClientAuth(self.name, self.cookie, self.key))
            self.reset()

        def set_name(self, name):
            self.create_key()
            self.name = name.split()[1]

        def set_cookie(self, cookie):
            self.cookie = cookie.split()[1]
            if self.cookie.endswith('=='):
                self.cookie = self.cookie[:-2]

        def add_key_line(self, line):
            self.key.append(line)

    from txtorcon.spaghetti import FSM, State, Transition
    init = State('init')
    got_name = State('got_name')
    got_cookie = State('got_cookie')
    reading_key = State('got_key')

    parser_state = ParserState()

    # initial state; we want "client-name" or it's an error
    init.add_transitions([
        Transition(got_name, lambda line: line.startswith('client-name '), parser_state.set_name),
        Transition(init, lambda line: not line.startswith('client-name '), parse_error),
    ])

    # next up is "descriptor-cookie" or it's an error
    got_name.add_transitions([
        Transition(got_cookie, lambda line: line.startswith('descriptor-cookie '), parser_state.set_cookie),
        Transition(init, lambda line: not line.startswith('descriptor-cookie '), parse_error),
    ])

    # the "interesting bit": there's either a client-name if we're a
    # "basic" file, or an RSA key (with "client-key" before it)
    got_cookie.add_transitions([
        Transition(reading_key, lambda line: line.startswith('client-key'), None),
        Transition(got_name, lambda line: line.startswith('client-name '), parser_state.set_name),
    ])

    # if we're reading an RSA key, we accumulate it in current_key.key
    # until we hit a line starting with "client-name"
    reading_key.add_transitions([
        Transition(reading_key, lambda line: not line.startswith('client-name'), parser_state.add_key_line),
        Transition(got_name, lambda line: line.startswith('client-name '), parser_state.set_name),
    ])

    # create our FSM and parse the data
    fsm = FSM([init, got_name, got_cookie, reading_key])
    for line in stream.readlines():
        fsm.process(line.strip())

    parser_state.create_key()  # make sure we get the "last" one
    return parser_state.keys


class OnionAuthNone(object):
    def __init__(self, uri):
        self._uri = uri

    def uri(self, client):
        if client is not None:
            msg = "client= specified for non-authenticated service"
            raise RuntimeError(msg)
        if self._uri is None:
            raise RuntimeError("No URI available yet")
        return self._uri


class OnionService(object):

    def __init__(self, torconfig, ports, is_ephemeral=True, authentication=None, directory=None):
        self.ports = ports
        self.ephemeral = is_ephemeral
        # private state:
        self._authentication = authentication
        if self._authentication is None:
            self._authentication = OnionAuthNone(None)
        self._tor_config = torconfig

    def uri(self, client=None):
        """
        Returns the onion URI for the given client. The client is only
        relevant for authenticated services.
        """
        return self._authentication.uri(client)


@defer.inlineCallbacks
def create_authenticated_filesystem_onion_service(
        reactor, torconfig, ports, directory,
        auth):  # StealthAuth(['bob', 'alice']) or BasicAuth(['bob', 'alice'])
    pass


@defer.inlineCallbacks
def create_filesystem_onion_service(
        reactor, torconfig, ports, directory):
        #        auth=NoAuth(),#_type='none',
        # or:        auth=StealthAuth(['bob', 'alice']),
        # or:        auth=BasicAuth(['bob', 'alice']),
        # XXX really? await_upload=True):
    pass


# XXX
# kurt: so the "auth" is either NoAuth(), StealthAuth(), BasicAuth()
# -> can we do the same thing for ephemeral/not

# kurt: private_key + discard_key --> can combine?
# or: can we "unify" the private_key to enum: "don't have key", "don't want key", "here's key"
#     -> sounds like tears. does it want "some kind of object" to encode these desires?
# or: pass **kwargs OR dict, and if 'private_key' in it, you want it
# back; and if it's already a keyblob, you're a winner
# kurt doesn't like magic **kwargs, tho.

_THROW_AWAY = object()


@defer.inlineCallbacks
# not supported by tor, but might be ...
def create_authenticated_ephemeral_onion_service():
    pass


@defer.inlineCallbacks
def create_ephemeral_onion_service(
        reactor, torconfig, ports,
        private_key=_THROW_AWAY,  # if None, means "create, but don't send back".
        detach=None,  # XXX probably False by default
        await_upload=True):
    """
    This yields a new IOnionService if ``auth_type`` is "none" (the
    defalt) otherwise yields an IAuthenticatdOnionService (if
    ``auth_type`` is "basic" or "stealth"). In either case, the
    Deferred returned only fires once Tor has been configured *and* at
    least one descriptor has been successfully uploaded.

    :param ports: a list of "ports" lines (str), which look like: ``80
        127.0.0.1:1234`` or more generally ``public_port
        host:local_port`` (XXX what about unix sockets?)
    :type ports: list of str

    :param directory: the directory to use that contains `hostname`
        and ``private_key`` files. If one is not suppied, it will be created
        (honoring ``$TMPDIR``, if set)
    :type directory: str

    :param ephemeral: If True, uses ADD_ONION command; otherwise, uses
    the HiddenServiceDir configuration option (and creates/uses a
        temporary or permanent directory to pass private keys to/from
        Tor.  Note that ADD_ONION doesn't yet allow passing any
        authentication options, so this is only allowed if auth_type
        == "none"
    :type ephemeral: bool

    :param auth_type: 'basic' (the default) or 'stealth'
    :type auth_type: str

    :param await_upload: if True (the default) wait for at least one
        descriptor upload to succeed before the callback fires. The hidden
        service will not be reachable by any clients until 1 or more
        descriptors are uploaded.
    :type await_upload: bool
    """
    # validate args
    acceptable_auth = ['none', 'basic', 'stealth']
    if auth_type not in acceptable_auth:
        raise ValueError(
            "auth_type must be one of: {}".format(
                ", ".join(acceptable_auth),
            )
        )
    if auth_type != "none" and ephemeral:
        raise ValueError(
            "ephemeral onion services only work with auth_type='none'"
        )

    if ephemeral:
        detach = bool(detach)  # False by default
        discard_key = bool(discard_key)  # False by default
    else:
        if detach is not None:
            raise ValueError(
                "'detach' can only be specified for ephemeral services"
            )
        if discard_key is not None:
            raise ValueError(
                "'discard_key' can only be specified for ephemeral services"
            )

    # there are the following types of hidden/onion services we can
    # create:
    # ephemeral:
    #   - no auth -> EphemeralHiddenService instance
    # filesystem:
    #   - no auth -> HiddenService instance
    #   - basic auth -> AuthenticatedHiddenService instance
    #   - stealth auth -> AuthenticatdHiddenService instance
    # So, "onion" wil be one of the above after this "case" statement

    if auth_type == 'none':
        if ephemeral:
            hs = yield EphemeralHiddenService.create(
                torconfig, ports,
                detach=detach,
                discard_key=discard_key,
            )
            defer.returnValue(hs)
            return

        else:
            if directory is None:
                # XXX when to delete this?
                directory = tempfile.mkdtemp()

            # XXX should be a .create() call
            hs = FilesystemHiddenService(
                torconfig, directory, ports,
            )
            torconfig.HiddenServices.append(hs)
            # listen for the descriptor upload event
            info_callback = defer.Deferred()

            def info_event(msg):
                # XXX giant hack here; Right Thing would be to implement a
                # "real" event in Tor and listen for that.
                if 'Service descriptor (v2) stored' in msg:
                    info_callback.callback(None)
            torconfig.protocol.add_event_listener('INFO', info_event)

            yield torconfig.save()
            yield info_callback  # awaits an INFO log-line from Tor .. sketchy
            torconfig.protocol.remove_event_listener('INFO', info_event)

            defer.returnValue(hs)
            return

    elif auth_type == 'basic':
        raise NotImplementedError()
    elif auth_type == 'stealth':
        raise NotImplementedError()
