#!/usr/bin/python3
import sys
import struct
import wrapper
import threading
import time
from wrapper import recv_from_any_link, send_to_link, get_switch_mac, get_interface_name

own_bridge_id = 0
root_bridge_id = 0
root_path_cost = 0
root_port = -1
vlan_table = []
bpdu_mac = struct.pack('!H', 0x0180) + struct.pack('!H', 0xC200) + struct.pack('!H', 0x0000)
bpdu_mac_string = ':'.join(f'{b:02x}' for b in bpdu_mac)

def parse_ethernet_header(data):
    # Unpack the header fields from the byte array
    #dest_mac, src_mac, ethertype = struct.unpack('!6s6sH', data[:14])
    dest_mac = data[0:6]
    src_mac = data[6:12]
    
    # Extract ethertype. Under 802.1Q, this may be the bytes from the VLAN TAG
    ether_type = (data[12] << 8) + data[13]

    vlan_id = -1
    # Check for VLAN tag (0x8100 in network byte order is b'\x81\x00')
    if ether_type == 0x8200:
        vlan_tci = int.from_bytes(data[14:16], byteorder='big')
        vlan_id = vlan_tci & 0x0FFF  # extract the 12-bit VLAN ID
        ether_type = (data[16] << 8) + data[17]

    return dest_mac, src_mac, ether_type, vlan_id

def create_vlan_tag(vlan_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used
    return struct.pack('!H', 0x8200) + struct.pack('!H', vlan_id & 0x0FFF)

def create_bdpu_data(port_id):
    # 0x8100 for the Ethertype for 802.1Q
    # vlan_id & 0x0FFF ensures that only the last 12 bits are used             
    return struct.pack('!H', root_bridge_id) + struct.pack('!H', root_path_cost) + struct.pack('!H', own_bridge_id) + struct.pack('!H', port_id)


def get_data_from_bpdu(data):
    return struct.unpack('!HHHH', data)

def send_bpdu_packet(port):
    send_to_link(port, 20, bpdu_mac + get_switch_mac() + create_bdpu_data(port))

def send_bdpu_every_sec():
    while True:
        # TODO Send BDPU every second if necessary
        if own_bridge_id == root_bridge_id:
            for index, port in enumerate(vlan_table):
                if port == 'T':
                    send_bpdu_packet(index)
        time.sleep(1)

def main():
    # init returns the max interface number. Our interfaces
    # are 0, 1, 2, ..., init_ret value + 1
    switch_id = sys.argv[1]

    num_interfaces = wrapper.init(sys.argv[2:])
    interfaces = range(0, num_interfaces)

    print("# Starting switch with id {}".format(switch_id), flush=True)
    print("[INFO] Switch MAC", ':'.join(f'{b:02x}' for b in get_switch_mac()))


    # Printing interface names
    for i in interfaces:
        print(get_interface_name(i))
        
    #initialising mac table dictionary
    MAC_table = {}
    
    with open("./configs/switch" + str(switch_id) + '.cfg', "r") as file:
        lines = file.readlines()
        for line in lines:
            x = line.split(' ')
            if len(x) > 1:
                vlan_table.append(x[1].strip())
            else:
                switch_priority = int(x[0].strip())
                
    # for port in vlan_table:
    #     if port == 'T':
    #         port = 'B'
    global own_bridge_id    
    global root_bridge_id
    global root_path_cost   
    global root_port
    own_bridge_id = switch_priority
    root_bridge_id = own_bridge_id
    root_path_cost = 0
    
    # if own_bridge_id == root_bridge_id:
    #     for port in vlan_table:
    #         if port == 'B':
    #             port = 'T'
    
    # Create and start a new thread that deals with sending BDPU
    t = threading.Thread(target=send_bdpu_every_sec)
    t.start()
    
    while True:
        # Note that data is of type bytes([...]).
        # b1 = bytes([72, 101, 108, 108, 111])  # "Hello"
        # b2 = bytes([32, 87, 111, 114, 108, 100])  # " World"
        # b3 = b1[0:2] + b[3:4].
        interface, data, length = recv_from_any_link()

        dest_mac, src_mac, ethertype, vlan_id = parse_ethernet_header(data)
        

        # Print the MAC src and MAC dst in human readable format
        dest_mac = ':'.join(f'{b:02x}' for b in dest_mac)
        src_mac = ':'.join(f'{b:02x}' for b in src_mac)

        # Note. Adding a VLAN tag can be as easy as
        # tagged_frame = data[0:12] + create_vlan_tag(10) + data[12:]
        

        print(f'Destination MAC: {dest_mac}')
        print(f'Source MAC: {src_mac}')
        print(f'EtherType: {ethertype}')

        print("Received frame of size {} on interface {}".format(length, interface), flush=True)

        # TODO: Implement forwarding with learning
        if dest_mac == bpdu_mac_string:
            bpdu_root_bridge_id, bpdu_root_path_cost, bdpu_bridge_id, bpdu_port_id = get_data_from_bpdu(data[12:])
            if bpdu_root_bridge_id < root_bridge_id:
                old_root_bridge_id = root_bridge_id
                root_bridge_id = bpdu_root_bridge_id
                root_path_cost = bpdu_root_path_cost + 10
                root_port = interface
                if old_root_bridge_id == own_bridge_id:
                    for index, port in enumerate(vlan_table):
                        if port == 'T' and index != interface:
                            vlan_table[index] = 'B'
                if vlan_table[interface] == 'B':
                    vlan_table[interface] = 'T'
                for index, port in enumerate(vlan_table):
                    if port == 'T':
                        send_bpdu_packet(index)
            elif root_bridge_id == bpdu_root_bridge_id:
                if interface == root_port and bpdu_root_path_cost + 10 < root_path_cost:
                    root_path_cost = bpdu_root_path_cost + 10
                elif interface != root_port:
                    if bpdu_root_path_cost > root_path_cost:
                        if vlan_table[interface] == 'B':
                            vlan_table[interface] = 'T'
            elif bdpu_bridge_id == own_bridge_id:
                if vlan_table[interface] == 'T':
                    vlan_table[interface] = 'B'


            if own_bridge_id == root_bridge_id:
                for index, port in enumerate(vlan_table):
                    if port == 'B':
                        vlan_table[index] = 'T'
            continue
        
        #adding src with interface in mac table if not there
        from_trunk = False
        if vlan_id != -1:
            from_trunk = True

        if not from_trunk:
            tagged_frame = data[0:12] + create_vlan_tag(int(vlan_table[interface])) + data[12:]
            
            
        if not src_mac in MAC_table:
            MAC_table[src_mac] = interface
            
        if dest_mac in MAC_table:
            if vlan_table[MAC_table[dest_mac]] == 'B':
                continue
            if from_trunk and vlan_table[MAC_table[dest_mac]] == 'T':
                send_to_link(MAC_table[dest_mac], length, data)
            if from_trunk and vlan_table[MAC_table[dest_mac]] != 'T' and vlan_table[MAC_table[dest_mac]] == str(vlan_id):
                send_to_link(MAC_table[dest_mac], length - 4, data[:12] + data[16:])
            if not from_trunk and vlan_table[MAC_table[dest_mac]] == 'T':
                send_to_link(MAC_table[dest_mac], length + 4, tagged_frame)
            if not from_trunk and vlan_table[MAC_table[dest_mac]] != 'T' and vlan_table[MAC_table[dest_mac]] == vlan_table[interface]:
                send_to_link(MAC_table[dest_mac], length, data)
        else:
            for i in interfaces:
                if i != interface:
                    if vlan_table[i] == 'B':
                        continue
                    if from_trunk and vlan_table[i] == 'T':
                        send_to_link(i, length, data)
                    if from_trunk and vlan_table[i] != 'T' and vlan_table[i] == str(vlan_id):
                        send_to_link(i, length - 4, data[:12] + data[16:])
                    if not from_trunk and vlan_table[i] == 'T':
                        send_to_link(i, length + 4, tagged_frame)
                    if not from_trunk and vlan_table[i] != 'T' and vlan_table[i] == vlan_table[interface]:
                        send_to_link(i, length, data)
        
        # TODO: Implement VLAN support
        
        # TODO: Implement STP support

        # data is of type bytes.
        # send_to_link(i, length, data)

if __name__ == "__main__":
    main()