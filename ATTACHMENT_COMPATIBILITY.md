# Photon attachment compatibility in Task A

The current installed adapter sends local filesystem paths to the sidecar's
`/send-attachment` route. In the proposed protected topology, a Hermes caller
could use that route to make the broker UID read private files. The staged
upstream patch removes the route and makes the Hermes adapter's media methods
return an explicit disabled result in Task A mode. The restricted front has
no file, URL, or media-byte field and no generic forwarding endpoint.

This changes behavior: outbound images, voice notes, documents, video,
rich-link cards, native polls, tapbacks, and typing are not guaranteed by the
Task A restricted interface. Ordinary bounded text replies tied to admitted
events are the only intended outbound capability. Inbound attachments are
also outside the current Task A allowlisted text event flow. A text URL remains
text; it is not fetched or rendered as a privileged rich link by the front.

Any later attachment feature needs a separate reviewed design: an explicitly
bounded byte stream or broker-owned attachment identifier, media-type and size
limits, fixed approved destination, no caller-controlled broker filesystem
path, and negative tests for symlinks, `/proc`, credentials, retries and
partial sends. No such feature is enabled by this candidate.
# v0.1.3 note

The protected sidecar does not read attachment bytes for Task A events.
Oversized or non-text SDK events receive an explicit durable rejection and
no read receipt. Hermes still cannot provide an arbitrary filesystem path or
invoke `/send-attachment` through the restricted interface. Live attachment
and rich media compatibility remains separately unverified.

