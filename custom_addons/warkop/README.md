# Operasional Warkop H. Mahmud
- **FR-01:** saldo stok per cabang, laporan _stock opname_ dan _waste_,
  verifikasi Team Leader, persetujuan Manajer Operasional, serta riwayat
  audit penyesuaian.
- **FR-02:** impor penjualan POS dengan deteksi duplikasi, parameter
  _safety stock_, rekomendasi pembelian, dan persetujuan PO berdasarkan nilai.
- **FR-03:** laporan tutup kas per _shift_, verifikasi Team Leader, dan
  konsolidasi kas harian lintas cabang.
- **FR-04:** resep menu, harga bahan terbaru, toleransi _waste_, HPP, dan
  perhitungan margin kontribusi.

Alur persetujuan tetap mengikuti pembagian aktor:

1. Karyawan Operasional membuat dan mengajukan laporan.
2. Team Leader memverifikasi atau mengembalikan laporan.
3. Manajer Operasional menyetujui penyesuaian stok.
4. Manajer Purchasing mengelola rekomendasi dan PO bernilai rendah.
5. Owner menyetujui atau menolak PO yang melewati batas persetujuan.
6. Manajer Admin dan Keuangan memposting konsolidasi kas.

## Instalasi

```text
docker compose run --rm web odoo -d odoo_app -i warkop --stop-after-init
```
