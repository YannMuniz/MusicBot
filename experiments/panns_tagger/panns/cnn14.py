"""Cnn14 (PANNs, Kong et al. 2020; MIT) — apenas o caminho de INFERÊNCIA, com front-end log-mel em torch (sem torchlibrosa).

O front-end reproduz o do checkpoint: 32 kHz, janela de Hann (periódica) de 1024, hop 320, centro com reflexão, espectro de
potência, banco mel de 64 bandas lido do PRÓPRIO checkpoint (logmel_extractor.melW), 10*log10(max(x, 1e-10)).
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

SR = 32000
N_FFT, HOP = 1024, 320


class ConvBlock(nn.Module):
    def __init__(self, cin, cout):
        super().__init__()
        self.conv1 = nn.Conv2d(cin, cout, kernel_size=3, stride=1, padding=1, bias=False)
        self.conv2 = nn.Conv2d(cout, cout, kernel_size=3, stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(cout)
        self.bn2 = nn.BatchNorm2d(cout)

    def forward(self, x, pool):
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        return F.avg_pool2d(x, kernel_size=pool)


class Cnn14(nn.Module):
    def __init__(self, classes_num=527):
        super().__init__()
        self.bn0 = nn.BatchNorm2d(64)
        self.conv_block1 = ConvBlock(1, 64)
        self.conv_block2 = ConvBlock(64, 128)
        self.conv_block3 = ConvBlock(128, 256)
        self.conv_block4 = ConvBlock(256, 512)
        self.conv_block5 = ConvBlock(512, 1024)
        self.conv_block6 = ConvBlock(1024, 2048)
        self.fc1 = nn.Linear(2048, 2048, bias=True)
        self.fc_audioset = nn.Linear(2048, classes_num, bias=True)
        self.register_buffer("mel_w", torch.zeros(N_FFT // 2 + 1, 64))
        self.register_buffer("window", torch.hann_window(N_FFT, periodic=True))

    def logmel(self, wav):
        """wav: (B, N) a 32 kHz -> (B, T, 64)."""
        spec = torch.stft(wav, n_fft=N_FFT, hop_length=HOP, win_length=N_FFT, window=self.window, center=True,
                          pad_mode="reflect", return_complex=True)
        power = spec.real ** 2 + spec.imag ** 2
        mel = power.transpose(1, 2) @ self.mel_w
        return 10.0 * torch.log10(torch.clamp(mel, min=1e-10))

    def forward(self, wav):
        x = self.logmel(wav)[:, None]            # (B,1,T,64)
        x = x.transpose(1, 3)
        x = self.bn0(x)
        x = x.transpose(1, 3)
        for blk, pool in ((self.conv_block1, 2), (self.conv_block2, 2), (self.conv_block3, 2), (self.conv_block4, 2), (self.conv_block5, 2), (self.conv_block6, 1)):
            x = blk(x, pool)
        x = torch.mean(x, dim=3)
        x = torch.max(x, dim=2)[0] + torch.mean(x, dim=2)
        x = F.relu(self.fc1(x))
        return torch.sigmoid(self.fc_audioset(x))
