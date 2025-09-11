{ pkgs }: {
  deps = [
    pkgs.python39
    pkgs.ffmpeg
    pkgs.python39Packages.pip
  ];
}
