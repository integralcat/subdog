# Modern Web Routing: From DNS to Application Response

This document explains the journey of a web request in modern infrastructure,
strictly separated by protocol layers. It moves beyond the legacy model (where
one IP address equaled one server) to today's multi-tenant, edge-based
architectures used by companies like Google, Amazon, and Cloudflare.

> DNS is Not a "Server locator" it's more like "here is an entry point into
> distributed systems"

## 1. DNS Layer: Resolution and Traffic Steering

Before any connection is made, the client (browser or `curl`) must translate
a human-readable hostname (e.g., `www.google.com`) into an IP address.

### A and AAAA Records

- **A Record:** Maps a hostname to an IPv4 address (e.g., `142.250.190.68`).
- **AAAA Record:** Maps a hostname to an IPv6 address (e.g., `2607:f8b0:4003:c05::68`).

### Load Balancing at DNS

Modern DNS does not just return a static IP; it returns a _list_ of IPs or
different IPs based on the user's location (Geo-DNS). This is the first layer
of load balancing.

**Demonstration:**
Run `dig` (or `nslookup`) against a major site like Google. You will often
see multiple IP addresses returned. The client typically picks the first one,
but if that fails, it tries the others.

```bash
$ dig +short www.google.com
142.250.190.68
142.250.190.36
142.250.190.132
```

### TTL (Time To Live)

The TTL dictates how long this mapping is cached. Low TTLs (e.g., 60 seconds)
allow engineers to quickly shift traffic away from a down data center by
updating DNS records.

---

## 2. TCP Layer: Establishing the Pipe

Once the client has an IP address (e.g., `142.250.190.68`), it initiates a TCP connection.

### The Handshake (SYN, SYN-ACK, ACK)

The client attempts to connect to the target IP on port 443 (for HTTPS).

1.  **SYN:** Client sends a "synchronize" packet to the IP.
2.  **SYN-ACK:** Server acknowledges.
3.  **ACK:** Client acknowledges back.

### The Limitation of TCP

At this layer, **the server only knows the destination IP address and port**.
It does _not_ know which website the client wants to see. If `142.250.190.68`
hosts `google.com`, `gmail.com`, and `youtube.com`, the TCP layer cannot
distinguish between them.

---

## 3. TLS Layer: The Secure Handshake & SNI

After TCP is established, the TLS (Transport Layer Security) handshake begins
to encrypt the connection. This is where modern routing diverges significantly
from legacy systems.

### SNI (Server Name Indication)

(SNI) is a TLS extension allowing a server to present multiple, distinct SSL
certificates for different websites on a single IP address. By sending the
hostname during the initial handshake, it enables secure, shared hosting,
preventing certificate mismatch errors.

In the past, a server needed a unique IP for every SSL certificate. Today, we
use **SNI**.
During the `ClientHello` (the first step of the TLS handshake), the client
sends the hostname it wants to connect to _in cleartext_ (or encrypted via ECH
in very new standards).

**Why this matters:**
Cloudflare, for example, might host 10,000 different websites on the generic IP
`104.21.55.2`. Without SNI, Cloudflare wouldn't know which SSL certificate to
present to the client.

### Certificate Validation & SANs

The server responds with a certificate. The client verifies:

1.  **Trust Chain:** Is it signed by a known Certificate Authority (CA)?
2.  **SAN (Subject Alternative Name):** Does the certificate actually
    list `www.google.com` as a valid owner?

**Demonstration:**
Use `openssl` or `curl -v` to see the SNI extension in action.

```bash
openssl s_client -connect google.com:443 -servername google.com
```

```bash
# We connect to a generic Google IP, but we MUST tell TLS we want "youtube.com"
$ curl -v --resolve www.youtube.com:443:142.250.190.68 https://www.youtube.com
```

In the output, look for:

> - TLSv1.3 (OUT), TLS handshake, Client hello (1):
> - ...
> - Server certificate:
> - subject: CN=\*.google.com

If the SNI matches the certificate provided, the secure tunnel is established.

---

## 4. HTTP Layer: The Application Request

Now that we have an encrypted tunnel to the correct IP, the client sends the actual HTTP request.

### The Host Header

The most critical component for routing at this layer is the `Host` header.

```http
GET /search?q=routing HTTP/1.1
Host: www.google.com
User-Agent: curl/7.64.1
Accept: */*
```

### Host Header vs. SNI

- **SNI (TLS Layer):** Tells the server "Which Certificate should I use?"
- **Host Header (HTTP Layer):** Tells the web server "Which application
  code should handle this request?"

While they usually match, they are distinct. Reverse proxies use the Host
header to route traffic to internal microservices (e.g., routing
`google.com/maps` to the Maps fleet and `google.com/search` to the Search
fleet).

---

## 5. Infrastructure: Reverse Proxies, CDNs, and Load Balancers

In modern architecture, the "server" you connected to is rarely the machine
that holds the data. It is an **Edge Node** or **Reverse Proxy**.

### The Edge (Termination)

Services like Cloudflare, AWS CloudFront, or an Nginx Ingress Controller terminate the connection.

1.  They handle the TCP connection.
2.  They perform the TLS decryption.
3.  They inspect the HTTP `Host` and `Path`.

### The Upstream (Backend)

Based on the `Host` header, the edge node creates a _new_ connection to a backend server (the "origin").

- Client <-> Edge (Public Internet, Encrypted)
- Edge <-> Backend App (Private Network, often plain HTTP or mTLS)

**Example:**
When you request `amazon.com`, you hit an Edge location near your city. That
edge node checks its cache. If the content isn't there, it acts as a client and
requests the data from a server in Virginia or Oregon.

---

## Summary: Old vs. New Architecture

| Feature      | Legacy Architecture      | Modern / Cloud Native                    |
| :----------- | :----------------------- | :--------------------------------------- |
| **Identity** | 1 IP Address = 1 Website | 1 IP Address = 10,000+ Websites          |
| **Routing**  | Done by IP address       | Done by SNI (TLS) and Host Header (HTTP) |
| **Scaling**  | Vertical (bigger server) | Horizontal (Anycast DNS, Load Balancers) |
| **SSL/TLS**  | One cert per IP          | SNI allows thousands of certs per IP     |
| **Location** | Server sits in one rack  | "Server" is a global fleet of edge nodes |

**Why IP is insufficient:**
In modern hosting (Kubernetes, Vercel, Cloudflare), the IP address identifies
the _load balancer_, not the application. You cannot "ping" a specific modern
application; you can only ping its entry point. The application itself exists
only as a configuration routed by the Host header.

---
