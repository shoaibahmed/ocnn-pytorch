import torch


class KeyLUT:

  def __init__(self):
    r256 = torch.arange(256, dtype=torch.int64)
    r512 = torch.arange(512, dtype=torch.int64)
    zero = torch.zeros(256, dtype=torch.int64)
    device = torch.device('cpu')

    self._encode = {device: (self.xyz2key(r256, zero, zero, 8),
                             self.xyz2key(zero, r256, zero, 8),
                             self.xyz2key(zero, zero, r256, 8))}
    self._decode = {device: self.key2xyz(r512, 9)}

  def encode_lut(self, device=torch.device('cpu')):
    if device not in self._encode:
      cpu = torch.device('cpu')
      self._encode[device] = tuple(e.to(device) for e in self._encode[cpu])
    return self._encode[device]

  def decode_lut(self, device=torch.device('cpu')):
    if device not in self._decode:
      cpu = torch.device('cpu')
      self._decode[device] = tuple(e.to(device) for e in self._decode[cpu])
    return self._decode[device]

  def xyz2key(self, x, y, z, depth):
    key = torch.zeros_like(x)
    for i in range(depth):
      mask = 1 << i
      key = (key | ((x & mask) << (2 * i + 2)) |
                   ((y & mask) << (2 * i + 1)) |
                   ((z & mask) << (2 * i + 0)))
    return key

  def key2xyz(self, key, depth):
    x = torch.zeros_like(key)
    y = torch.zeros_like(key)
    z = torch.zeros_like(key)
    for i in range(depth):
      x = x | ((key & (1 << (3 * i + 2))) >> (2 * i + 2))
      y = y | ((key & (1 << (3 * i + 1))) >> (2 * i + 1))
      z = z | ((key & (1 << (3 * i + 0))) >> (2 * i + 0))
    return x, y, z


_key_lut = KeyLUT()


def xyz2key(x, y, z, b=None, depth=16):
  r'''Encode x, y, z coordinates to the shuffled keys based on pre-computed
  look up tables. The speed of this function is much faster than the method 
  based on for-loop.

  Args: 
    x (torch.tensor): The x coordinate. 
    y (torch.tensor): The y coordinate.
    z (torch.tensor): The z coordinate. 
    b (torch.tensor or int): The batch index of the coordinates. If b is a 
        torch.tensor, the size of b must be the same as x, y, and z. 
    depth (int): The depth of the shuffled key, and must be smaller than 16.
  '''

  EX, EY, EZ = _key_lut.encode_lut(x.device)
  x, y, z = x.long(), y.long(), z.long()

  key = EX[x & 255] | EY[y & 255] | EZ[z & 255]
  if depth > 8:
    key16 = EX[x >> 8 & 255] | EY[y >> 8 & 255] | EZ[z >> 8 & 255]
    key = key16 << 24 | key

  if b is not None:
    b = b.long()
    key = b << 48 | key

  return key


def key2xyz(key, depth=16):
  r'''Decode the shuffled key to x, y, z coordinates and the batch index based 
  on pre-computed look up tables.

  Args: 
    key (torch.tensor): The shuffled key.
    depth (int): The depth of the shuffled key, and must be smaller than 16.
  '''
  DX, DY, DZ = _key_lut.decode_lut(key.device)
  x, y, z = torch.zeros_like(key), torch.zeros_like(key), torch.zeros_like(key)

  n = (depth + 2) // 3
  for i in range(n):
    k = key >> (i * 9) & 511
    x = x | (DX[k] << (i * 3))
    y = y | (DY[k] << (i * 3))
    z = z | (DZ[k] << (i * 3))

  b = key >> 48

  return x, y, z, b
