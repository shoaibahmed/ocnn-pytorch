import torch
import torch.nn
from typing import Optional

import ocnn
from ocnn.octree import Octree


class AutoEncoder(torch.nn.Module):

  def __init__(self, channel_in: int, channel_out: int, depth: int,
               full_depth: int = 2, feature: str = 'N'):
    super().__init__()
    self.channel_in = channel_in
    self.channel_out = channel_out
    self.depth = depth
    self.full_depth = full_depth
    self.feature = feature
    self.resblk_num = 3
    self.channels = [512, 512, 256, 256, 128, 128, 32, 32, 16, 16]

    # encoder
    self.conv1 = ocnn.modules.OctreeConvBnRelu(
        channel_in, self.channels[depth], nempty=False)
    self.encoder_blks = torch.nn.ModuleList([ocnn.modules.OctreeResBlocks(
        self.channels[d], self.channels[d], self.resblk_num, nempty=False)
        for d in range(depth, full_depth-1, -1)])
    self.downsample = torch.nn.ModuleList([ocnn.modules.OctreeConvBnRelu(
        self.channels[d], self.channels[d-1], kernel_size=[2], stride=2,
        nempty=False) for d in range(depth, full_depth, -1)])

    # decoder
    self.upsample = torch.nn.ModuleList([ocnn.modules.OctreeDeconvBnRelu(
        self.channels[d-1], self.channels[d], kernel_size=[2], stride=2,
        nempty=False) for d in range(full_depth+1, depth+1)])
    self.decoder_blks = torch.nn.ModuleList([ocnn.modules.OctreeResBlocks(
        self.channels[d], self.channels[d], self.resblk_num, nempty=False)
        for d in range(full_depth, depth+1)])

    # header
    self.predict = torch.nn.ModuleList([self._make_predict_module(
        self.channels[d], 2) for d in range(full_depth, depth + 1)])
    self.header = self._make_predict_module(self.channels[depth], channel_out)

  def _make_predict_module(self, channel_in, channel_out=2, num_hidden=64):
    return torch.nn.Sequential(
        ocnn.modules.Conv1x1BnRelu(channel_in, num_hidden),
        ocnn.modules.Conv1x1(num_hidden, channel_out, use_bias=True))

  def get_input_feature(self, octree: Octree):
    octree_feature = ocnn.modules.InputFeature(self.feature, nempty=False)
    out = octree_feature(octree)
    assert out.size(1) == self.channel_in
    return out

  def encoder_network(self, octree: Octree):
    convs = dict()
    depth, full_depth = self.depth, self.full_depth
    data = self.get_input_feature(octree)
    convs[depth] = self.conv1(data, octree, depth)
    for i, d in enumerate(range(depth, full_depth-1, -1)):
      convs[d] = self.encoder_blks[i](convs[d], octree)
      if d > full_depth:
        convs[d-1] = self.downsample[i](convs[d], octree)
    shape_code = torch.tanh(convs[depth])
    return shape_code

  def decoder_network(self, shape_code: torch.Tensor, octree: Octree,
                      update_octree: bool = False):
    logits = dict()
    deconv = shape_code
    depth, full_depth = self.depth, self.full_depth
    for i, d in enumerate(range(full_depth, depth+1)):
      deconv = self.decoder_blks[i](deconv, octree, d)
      if d > full_depth:
        deconv = self.upsample[i-1](deconv, octree, d)

      # predict the splitting label
      logit = self.predict[i](deconv)
      logits[d] = logit

      # update the octree according to predicted labels
      if update_octree:
        split = logit.argmax(1).int()
        octree.octree_split(split, d)
        if d < depth:
          octree.octree_grow(d + 1)

      # predict the signal
      if d == depth:
        signal = self.header(deconv)
        signal = torch.tanh(signal)
        signal = ocnn.nn.octree_depad(signal, octree, depth)
        if update_octree:
          octree.features[depth] = signal

    return {'logits': logits, 'signal': signal, 'octree_out': octree}

  def decode_code(self, shape_code):
    octree_out = self.init_octree(shape_code)
    out = self.decoder_network(shape_code, octree_out, update_octree=True)
    return out

  def init_octree(self, shape_code: torch.Tensor):
    device = shape_code.device
    node_num = 2 ** (3 * self.full_depth)
    batch_size = shape_code.size(0) // node_num
    octree = Octree(self.depth, self.full_depth, batch_size, device)
    for d in range(self.full_depth+1):
      octree.octree_grow_full(depth=d)
    return octree

  def forward(self, octree_in: Octree, octree_out: Optional[Octree] = None):
    r''''''

    shape_code = self.encoder_network(octree_in)

    update_octree = octree_out is None
    if update_octree:
      octree_out = self.init_octree(shape_code)

    out = self.decoder_network(shape_code, octree_out, update_octree)
    return out