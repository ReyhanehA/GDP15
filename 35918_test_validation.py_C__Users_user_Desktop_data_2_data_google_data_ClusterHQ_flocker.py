# Copyright ClusterHQ Inc.  See LICENSE file for details.

"""
Test validation of keys generated by flocker-ca.
"""

from __future__ import print_function

from OpenSSL.SSL import Context, TLSv1_METHOD, Error as SSLError

from twisted.internet.endpoints import (
    SSL4ServerEndpoint, connectProtocol, SSL4ClientEndpoint,
    )
from twisted.internet import reactor
from twisted.internet.defer import Deferred, gatherResults
from twisted.internet.protocol import Protocol, ServerFactory

from ...testtools import AsyncTestCase, find_free_port
from .._validation import (
    ControlServicePolicy, amp_server_context_factory, rest_api_context_factory,
    )
from ..testtools import get_credential_sets


EXPECTED_STRING = b"Mr. Watson, come here; I want to see you."


class SendingProtocol(Protocol):
    """
    Send a string.
    """
    def __init__(self):
        self.disconnected = Deferred()

    def connectionMade(self):
        self.factory.disconnects.append(self.disconnected)
        self.transport.write(EXPECTED_STRING)
        self.transport.loseConnection()

    def connectionLost(self, reason):
        self.disconnected.callback(None)


class ReceivingProtocol(Protocol):
    """
    Expect a string.

    :ivar Deferred result: Fires on receiving response or if disconnected
         before that.
    """
    def __init__(self):
        self.result = Deferred()
        self._buffer = b""

    def dataReceived(self, data):
        self._buffer += data

    def connectionLost(self, reason):
        if self._buffer == EXPECTED_STRING:
            self.result.callback("handshake!")
        else:
            self.result.errback(reason)


class PeerContextFactory(object):
    """
    A TLS context factory that provides a private key and certificate.
    """
    def __init__(self, flocker_credential):
        """
        :param FlockerCredential flocker_credential: Credentials to use.
        """
        self.flocker_credential = flocker_credential

    def getContext(self):
        ctx = Context(TLSv1_METHOD)
        ctx.use_certificate(self.flocker_credential.certificate.original)
        ctx.use_privatekey(self.flocker_credential.keypair.keypair.original)
        return ctx


class WaitForDisconnectsFactory(ServerFactory):
    """
    A factory for use with ``SendingProtocol`` that makes it possible to wait
    for all of the protocols that have been created to disconnect.
    """
    def __init__(self):
        self.disconnects = []

    def wait_for_disconnects(self):
        """
        :return: A ``Deferred`` that fires when all protocols which have been
            connected at the point of this call have disconnected.
        """
        return gatherResults(self.disconnects)


def start_tls_server(test, port, context_factory):
    """
    Start a TLS server on the given port.

    :param test: The test this is being run in.
    :param int port: Port to listen on.
    :param context_factory: Context factory to use.

    :return: ``Deferred`` that fires when port is open to connections.
    """
    server_endpoint = SSL4ServerEndpoint(reactor, port,
                                         context_factory,
                                         interface='127.0.0.1')
    server_factory = WaitForDisconnectsFactory.forProtocol(SendingProtocol)
    test.addCleanup(lambda: server_factory.wait_for_disconnects())
    d = server_endpoint.listen(server_factory)
    d.addCallback(lambda port: test.addCleanup(port.stopListening))
    return d


def make_validation_tests(context_factory_fixture,
                          good_certificate_name,
                          validator_is_client):
    """
    Create a ``TestCase`` for the validator of a specific certificate type.

    :param context_factory_fixture: Create a context factory that
         implements the required validation given a ``CredentialSet``,
         given a port number on localhost and a ``CertificateSet``. For
         server context factories the port number can be ignored.

    :param str good_certificate_name: Name of certificate (an attribute of
        ``CredentialSet``) that should validate successfully.

    :param bool validator_is_client: Whether or not the context factory
         being tested is a client.

    :return: ``TestCase``-subclass with tests for given validator.
    """
    # For purposes of selecting other certs, control and control_dns are
    # equivalent:
    non_bad = good_certificate_name
    if non_bad == "control_dns":
        non_bad = "control"
    bad_name, another_bad_name = {"user", "node", "control"}.difference(
        {non_bad})

    class ValidationTests(AsyncTestCase):
        """
        Tests to ensure correct validation of a specific type of certificate.

        :ivar CertificateSet good_ca: The certificates for the CA we expect.

        :ivar CertificateSet another_ca: A different CA's certificates.
        """
        def setUp(self):
            super(ValidationTests, self).setUp()
            self.good_ca, self.another_ca = get_credential_sets()

        def _handshake(self, credential):
            """
            Run a TLS handshake between a client and server, one of which is
            using the validation logic and the other the given credential.

            :param credential: The high-level credential to use.

            :return ``Deferred``: Fires when handshake succeeded or
                failed.
            """
            peer_context_factory = PeerContextFactory(credential.credential)

            port = find_free_port()[1]
            validating_context_factory = context_factory_fixture(
                port, self.good_ca)

            if validator_is_client:
                client_context_factory = validating_context_factory
                server_context_factory = peer_context_factory
            else:
                server_context_factory = validating_context_factory
                client_context_factory = peer_context_factory

            result = start_tls_server(self, port, server_context_factory)
            validating_endpoint = SSL4ClientEndpoint(
                reactor, "127.0.0.1", port, client_context_factory)
            client_protocol = ReceivingProtocol()
            result.addCallback(lambda _: connectProtocol(validating_endpoint,
                                                         client_protocol))
            result.addCallback(lambda _: client_protocol.result)
            return result

        def assert_validates(self, credential):
            """
            Asserts that a TLS handshake is successfully established between a
            client using the validation logic and a server based on the
            given credential.

            :param credential: The high-level credential to use.

            :return ``Deferred``: Fires on success.
            """
            d = self._handshake(credential)
            d.addCallback(self.assertEqual, "handshake!")
            return d

        def assert_does_not_validate(self, credential):
            """
            Asserts that a TLS handshake fails to happen between a client using
            the validation logic and a server based on the given
            credential.

            :param FlockerCredential credential: The private key/certificate
                to use for the server.

            :return ``Deferred``: Fires on success (i.e. if no TLS handshake is
                established).
            """
            return self.assertFailure(self._handshake(credential),
                                      SSLError)

        def test_same_ca_correct_type(self):
            """
            If the expected certificate type is generated by the same CA
            then the validator will successfully validate it.
            """
            return self.assert_validates(
                getattr(self.good_ca, good_certificate_name))

        def test_different_ca_correct_type(self):
            """
            If the expected certificate type is generated by a different
            CA then the validator will reject it.
            """
            return self.assert_does_not_validate(
                getattr(self.another_ca, good_certificate_name))

        def test_same_ca_wrong_type(self):
            """
            If the expected certificate is generated by the same CA but is of
            the wrong type the validator will reject it.
            """
            return self.assert_does_not_validate(
                getattr(self.another_ca, bad_name))

        def test_same_ca_another_wrong_type(self):
            """
            If the expected certificate is generated by the same CA but is of
            the wrong type the validator will reject it.

            This is different wrong type than ``test_same_ca_wrong_type``.
            """
            return self.assert_does_not_validate(
                getattr(self.another_ca, another_bad_name))

        def test_invalid_signature(self):
            """
            If a certificate of the correct type signed by the correct CA was
            modified somehow, validation fails since the signature is no
            longer valid.
            """
            credential = getattr(self.good_ca, good_certificate_name)
            x509 = credential.credential.certificate.original
            original_serial = x509.get_serial_number()
            # Mutate the X509 certificate, invalidating the certificate
            # authority's signature:
            x509.set_serial_number(123)
            # We reuse this object in future tests; hopefully resetting
            # this makes the signature valid again:
            self.addCleanup(x509.set_serial_number, original_serial)
            return self.assert_does_not_validate(credential)

    return ValidationTests


class ControlServicePolicyIPValidationTests(make_validation_tests(
        lambda port, good_ca: ControlServicePolicy(
            ca_certificate=good_ca.root.credential.certificate,
            # The exposed client credential isn't actually tested by these
            # tests, but is necessary for the code to run:
            client_credential=good_ca.user.credential).creatorForNetloc(
                b"127.0.0.1", port),
        # We are testing a client that is validating the control
        # service certificate:
        "control", validator_is_client=True)):
    """
    Tests for validation of the control service certificate by clients
    when the control service certificate was generated with IP as its
    hostname.
    """


class ControlServicePolicyDNSValidationTests(make_validation_tests(
        lambda port, good_ca: ControlServicePolicy(
            ca_certificate=good_ca.root.credential.certificate,
            # The exposed client credential isn't actually tested by these
            # tests, but is necessary for the code to run:
            client_credential=good_ca.user.credential).creatorForNetloc(
                b"localhost", port),
        # We are testing a client that is validating the control
        # service certificate:
        "control_dns", validator_is_client=True)):
    """
    Tests for validation of the control service certificate by clients
    when the control service certificate was generated with DNS name as
    its hostname.
    """


class AMPContextFactoryValidationTests(
        make_validation_tests(
            lambda port, good_ca: amp_server_context_factory(
                ca_certificate=good_ca.root.credential.certificate,
                # The exposed control credential isn't covered by these
                # tests, but is required for the tests to run:
                control_credential=good_ca.control),
            # We are testing a server validating node certificates:
            "node", validator_is_client=False)):
    """
    Tests for validation of node agents (i.e. AMP clients connecting to
    the control service).
    """


class RESTAPIContextFactoryValidationTests(
        make_validation_tests(
            lambda port, good_ca: rest_api_context_factory(
                ca_certificate=good_ca.root.credential.certificate,
                # The exposed control credential isn't covered by these
                # tests, but is required for the tests to run:
                control_credential=good_ca.control),
            # We are testing a server validating node certificates:
            "user", validator_is_client=False)):
    """
    Tests for the context factory that validates REST API clients.
    """