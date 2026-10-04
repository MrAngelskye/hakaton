import socket
print('IPv4 этого компьютера (выберите адрес Wi-Fi/Ethernet или Tailscale):')
addresses=set()
try:
    for _,_,_,_,addr in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):addresses.add(addr[0])
except OSError:pass
for ip in sorted(addresses):
    if not ip.startswith('127.'):print(f'http://{ip}:8000')
print('Точный адрес адаптера также можно посмотреть командой ipconfig.')
