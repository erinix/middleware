# -*- coding: utf-8 -*-
import re
import ipaddress
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models
from datastore import get_default_datastore
from datastore.config import ConfigStore


LAGG_PROTOCOL_MAP = {
    'failover': 'FAILOVER',
    'fec': 'ETHERCHANNEL',
    'lacp': 'LACP',
    'loadbalance': 'LOADBALANCE',
    'roundrobin': 'ROUNDROBIN',
    'none': 'NONE'
}


MEDIAOPT_MAP = {
    'full-duplex': 'FDX',
    'half-duplex': 'HDX'
}


CAPABILITY_MAP = {
    'rxcsum': ('RXCSUM',),
    'txcsum': ('TXCSUM',),
    'rxcsum6': ('RXCSUM_IPV6',),
    'txcsum6': ('TXCSUM_IPV6',),
    'tso': ('TSO4', 'TSO6'),
    'tso4': ('TSO4',),
    'tso6': ('TSO6',),
    'lro': ('LRO',)
}


class Migration(SchemaMigration):
    no_dry_run = True

    def forwards(self, orm):
        ds = get_default_datastore()
        cs = ConfigStore(ds)

        # Migrate global network configuration
        globalconf = orm.GlobalConfiguration.objects.order_by("-id")[0]
        cs.set('system.hostname', globalconf.gc_hostname + '.' + globalconf.gc_domain)
        cs.set('network.gateway.ipv4', globalconf.gc_ipv4gateway or None)
        cs.set('network.gateway.ipv6', globalconf.gc_ipv6gateway or None)
        cs.set('network.http_proxy', globalconf.gc_httpproxy or None)
        cs.set('network.dns.addresses', list(filter(None, [
            globalconf.gc_nameserver1 or None,
            globalconf.gc_nameserver2 or None,
            globalconf.gc_nameserver3 or None,
        ])))

        cs.set('network.netwait.enable', globalconf.gc_netwait_enabled)
        cs.set('network.netwait.addresses', globalconf.gc_netwait_ip.split())

        # Disable autoconfigure since it will be using data from this migration
        cs.set('network.autoconfigure', False)

        # Migrate hosts database
        for line in globalconf.gc_hosts.split('\n'):
            line = line.strip()
            if not line:
                continue

            items = line.split()
            name = items.pop(0)
            for addr in items:
                ds.upsert('network.hosts', name, {
                    'address': addr
                })

        # Migrate VLAN interfaces configuration
        unit = 0
        for i in orm.VLAN.objects.all():
            ds.insert('network.interfaces', {
                'id': 'vlan{0}'.format(unit),
                'type': 'VLAN',
                'enabled': True,
                'description': i.vlan_description,
                'vlan': {
                    'parent': i.vlan_pint,
                    'tag': i.vlan_tag
                }
            })

            unit += 1

        # Migrate LAGG interfaces configuration
        unit = 0
        for i in orm.LAGGInterface.objects.all():
            ds.insert('network.interfaces', {
                'id': 'lagg{0}'.format(unit),
                'type': 'LAGG',
                'enabled': True,
                'lagg': {
                    'protocol': LAGG_PROTOCOL_MAP[i.lagg_protocol],
                    'ports': [m.int_interface for m in i.lagg_interfacemembers_set.all()]
                }
            })

            unit += 1

        # Migrate IP configuration
        for i in orm.Interfaces.objects.all():
            aliases = []
            iface = ds.get_by_id('network.interfaces', i.int_interface)
            if not iface:
                iface = {
                    'enabled': True,
                }

            iface.update({
                'description': i.int_name,
                'dhcp': i.int_dhcp,
                'aliases': aliases
            })

            if i.int_ipv4address:
                aliases.append({
                    'type': 'INET',
                    'address': str(i.int_ipv4address),
                    'prefixlen': int(i.int_v4netmaskbit)
                })

            if i.int_ipv6address:
                aliases.append({
                    'type': 'INET6',
                    'address': str(i.int_ipv6address),
                    'prefixlen': int(i.int_v6netmaskbit)
                })

            for alias in i.alias_set.all():
                if alias.alias_v4address:
                    aliases.append({
                        'type': 'INET',
                        'address': str(alias.alias_v4address),
                        'prefixlen': int(alias.alias_v4netmaskbit)
                    })

                if alias.alias_v6address:
                    aliases.append({
                        'type': 'INET6',
                        'address': str(alias.alias_v6address),
                        'prefixlen': int(alias.alias_v6netmaskbit)
                    })

            m = re.search(r'mtu (\d+)', i.int_options)
            if m:
                iface['mtu'] = int(m.group(1))

            m = re.search(r'media (\w+)', i.int_options)
            if m:
                iface['media'] = m.group(1)

            m = re.search(r'mediaopt (\w+)', i.int_options)
            if m:
                opt = m.group(1)
                if opt in MEDIAOPT_MAP:
                    iface['mediaopts'] = [MEDIAOPT_MAP[opt]]

            # Try to read capabilities
            for k, v in CAPABILITY_MAP.items():
                if '-{0}'.format(k) in i.int_options:
                    l = iface.setdefault('capabilities', {}).setdefault('del', [])
                    l += v
                elif k in i.int_options:
                    l = iface.setdefault('capabilities', {}).setdefault('add', [])
                    l += v

            ds.upsert('network.interfaces', i.int_interface, iface)

        # Migrate static routes
        for i in orm.StaticRoute.objects.all():
            try:
                net = ipaddress.ip_network(i.sr_destination)
            except ValueError as e:
                print("Invalid network {0}: {1}".format(i.sr_destination, e))
                continue
            ds.insert('network.routes', {
                'network': str(net.network_address),
                'netmask': net.prefixlen,
                'gateway': i.sr_gateway,
                'type': 'INET'
            })

        ds.collection_record_migration('network.interfaces', 'freenas9_migration')
        ds.collection_record_migration('network.routes', 'freenas9_migration')
        ds.collection_record_migration('network.hosts', 'freenas9_migration')

    def backwards(self, orm):
        pass

    models = {
        u'network.alias': {
            'Meta': {'object_name': 'Alias'},
            'alias_interface': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['network.Interfaces']"}),
            'alias_v4address': ('freenasUI.contrib.IPAddressField.IP4AddressField', [], {'default': "''", 'blank': 'True'}),
            'alias_v4netmaskbit': ('django.db.models.fields.CharField', [], {'default': "''", 'max_length': '3', 'blank': 'True'}),
            'alias_v6address': ('freenasUI.contrib.IPAddressField.IP6AddressField', [], {'default': "''", 'blank': 'True'}),
            'alias_v6netmaskbit': ('django.db.models.fields.CharField', [], {'default': "''", 'max_length': '3', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'})
        },
        u'network.globalconfiguration': {
            'Meta': {'object_name': 'GlobalConfiguration'},
            'gc_domain': ('django.db.models.fields.CharField', [], {'default': "'local'", 'max_length': '120'}),
            'gc_hostname': ('django.db.models.fields.CharField', [], {'default': "'nas'", 'max_length': '120'}),
            'gc_hosts': ('django.db.models.fields.TextField', [], {'default': "''", 'blank': 'True'}),
            'gc_httpproxy': ('django.db.models.fields.CharField', [], {'max_length': '255', 'blank': 'True'}),
            'gc_ipv4gateway': ('freenasUI.contrib.IPAddressField.IP4AddressField', [], {'default': "''", 'blank': 'True'}),
            'gc_ipv6gateway': ('freenasUI.contrib.IPAddressField.IP6AddressField', [], {'default': "''", 'blank': 'True'}),
            'gc_nameserver1': ('freenasUI.contrib.IPAddressField.IPAddressField', [], {'default': "''", 'blank': 'True'}),
            'gc_nameserver2': ('freenasUI.contrib.IPAddressField.IPAddressField', [], {'default': "''", 'blank': 'True'}),
            'gc_nameserver3': ('freenasUI.contrib.IPAddressField.IPAddressField', [], {'default': "''", 'blank': 'True'}),
            'gc_netwait_enabled': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'gc_netwait_ip': ('django.db.models.fields.CharField', [], {'max_length': '300', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'})
        },
        u'network.interfaces': {
            'Meta': {'ordering': "['int_interface']", 'object_name': 'Interfaces'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'int_dhcp': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'int_interface': ('django.db.models.fields.CharField', [], {'max_length': '300'}),
            'int_ipv4address': ('freenasUI.contrib.IPAddressField.IPAddressField', [], {'default': "''", 'blank': 'True'}),
            'int_ipv6address': ('freenasUI.contrib.IPAddressField.IPAddressField', [], {'default': "''", 'blank': 'True'}),
            'int_ipv6auto': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'int_name': ('django.db.models.fields.CharField', [], {'max_length': "'120'"}),
            'int_options': ('django.db.models.fields.CharField', [], {'max_length': '120', 'blank': 'True'}),
            'int_v4netmaskbit': ('django.db.models.fields.CharField', [], {'default': "''", 'max_length': '3', 'blank': 'True'}),
            'int_v6netmaskbit': ('django.db.models.fields.CharField', [], {'default': "''", 'max_length': '4', 'blank': 'True'})
        },
        u'network.lagginterface': {
            'Meta': {'ordering': "['lagg_interface']", 'object_name': 'LAGGInterface'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'lagg_interface': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['network.Interfaces']", 'unique': 'True'}),
            'lagg_protocol': ('django.db.models.fields.CharField', [], {'max_length': '120'})
        },
        u'network.lagginterfacemembers': {
            'Meta': {'ordering': "['lagg_interfacegroup']", 'object_name': 'LAGGInterfaceMembers'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'lagg_deviceoptions': ('django.db.models.fields.CharField', [], {'max_length': '120'}),
            'lagg_interfacegroup': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['network.LAGGInterface']"}),
            'lagg_ordernum': ('django.db.models.fields.IntegerField', [], {}),
            'lagg_physnic': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '120'})
        },
        u'network.staticroute': {
            'Meta': {'ordering': "['sr_destination', 'sr_gateway']", 'object_name': 'StaticRoute'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'sr_description': ('django.db.models.fields.CharField', [], {'max_length': '120', 'blank': 'True'}),
            'sr_destination': ('django.db.models.fields.CharField', [], {'max_length': '120'}),
            'sr_gateway': ('freenasUI.contrib.IPAddressField.IP4AddressField', [], {'max_length': '120'})
        },
        u'network.vlan': {
            'Meta': {'ordering': "['vlan_vint']", 'object_name': 'VLAN'},
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'vlan_description': ('django.db.models.fields.CharField', [], {'max_length': '120', 'blank': 'True'}),
            'vlan_pint': ('django.db.models.fields.CharField', [], {'max_length': '300'}),
            'vlan_tag': ('django.db.models.fields.PositiveIntegerField', [], {}),
            'vlan_vint': ('django.db.models.fields.CharField', [], {'max_length': '120'})
        }
    }

    complete_apps = ['network']
